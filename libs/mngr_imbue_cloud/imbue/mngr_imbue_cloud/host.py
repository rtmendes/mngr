"""Host class for imbue_cloud-leased agents.

Subclasses mngr's ``Host`` to adopt a pool host's pre-baked agent under the
caller's chosen name. Overrides four methods on the standard create pipeline
so ``mngr create --provider imbue_cloud_<account> --new-host`` runs end-to-end
without needing a separate "claim" verb:

- ``set_env_vars`` merges with the pre-baked ``/mngr/env`` instead of clobbering it
- ``create_agent_work_dir`` returns the pre-baked work_dir (no transfer)
- ``create_agent_state`` reuses the pre-baked agent id and overwrites the
  pre-baked ``data.json`` with the caller's name + labels + freshly assembled
  command
- ``provision_agent`` only writes the agent env file (and patches the claude
  config when ``ANTHROPIC_API_KEY`` is set in env); the pool host is already
  fully provisioned, so all other provisioning steps are skipped.
"""

import json as _json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field

from imbue.mngr.config.data_types import MngrContext
from imbue.mngr.hosts.host import Host
from imbue.mngr.interfaces.agent import AgentInterface
from imbue.mngr.interfaces.host import CreateAgentOptions
from imbue.mngr.interfaces.host import CreateWorkDirResult
from imbue.mngr.interfaces.host import OnlineHostInterface
from imbue.mngr.primitives import AgentId
from imbue.mngr.primitives import AgentName


class ImbueCloudHost(Host):
    """A leased pool host.

    The pre-baked agent's id is captured at lease time so ``create_agent_state``
    can adopt that agent under the caller's name instead of generating a new id.
    """

    pre_baked_agent_id: AgentId | None = Field(
        default=None,
        frozen=True,
        description=(
            "Agent id of the agent that was pre-provisioned on this pool host. "
            "Set by the provider when the host is created via lease."
        ),
    )
    lease_db_id: str | None = Field(
        default=None,
        frozen=True,
        description="Database id of this lease (UUID returned by /hosts/lease).",
    )

    def set_env_vars(self, env: Mapping[str, str]) -> None:
        """Merge ``env`` into the pre-baked ``/mngr/env`` instead of overwriting.

        The pool host's host env file already contains values that the agent
        runtime needs (``MNGR_HOST_DIR``, ``MNGR_PREFIX``, etc.). The standard
        ``Host.set_env_vars`` would clobber them, so we read-modify-write to
        keep the pre-baked entries that the caller didn't override.
        """
        if not env:
            return
        existing = self.get_env_vars()
        existing.update(env)
        super().set_env_vars(existing)

    def create_agent_work_dir(
        self,
        host: OnlineHostInterface,
        path: Path,
        options: CreateAgentOptions,
    ) -> CreateWorkDirResult:
        """No-op transfer: return the pre-baked work_dir recorded in data.json.

        The pool-baking step already ran ``mngr create`` with the requested
        repo+branch, so the work_dir on the leased container is wherever
        the FCT template's ``target_path`` placed it (``/code/`` for the
        vultr template, etc.). We pull the path out of the pre-baked
        ``data.json`` rather than reconstructing it, so this stays correct
        no matter which template the pool host was baked from.

        The caller's source ``path`` (from their laptop) is intentionally
        ignored -- ``mngr create --provider imbue_cloud_*`` is meaningful
        only when the pre-baked repo matches what the caller asked for, and
        ``LeaseAttributes`` (passed via ``--build-arg``) are how the
        connector enforces that match.
        """
        if self.pre_baked_agent_id is None:
            raise RuntimeError(
                "ImbueCloudHost.create_agent_work_dir requires pre_baked_agent_id; "
                "this host was constructed outside the lease flow."
            )
        data_path = self.host_dir / "agents" / str(self.pre_baked_agent_id) / "data.json"
        try:
            data = _json.loads(self.read_text_file(data_path))
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Pre-baked agent data.json not found at {data_path} on leased host {self.id}; "
                "the pool host was not properly provisioned."
            ) from exc
        recorded_work_dir = data.get("work_dir")
        if not isinstance(recorded_work_dir, str) or not recorded_work_dir:
            raise RuntimeError(f"Pre-baked agent data.json at {data_path} is missing a 'work_dir' field")
        return CreateWorkDirResult(path=Path(recorded_work_dir))

    def create_agent_state(
        self,
        work_dir_path: Path,
        options: CreateAgentOptions,
        created_branch_name: str | None = None,
    ) -> AgentInterface:
        """Adopt the pre-baked agent under the caller's name + labels.

        Forces ``options.agent_id`` to the pre-baked id (raising if the caller
        passed a conflicting one) so the standard parent implementation
        rewrites the existing ``data.json`` with the caller's name, labels,
        and a freshly assembled command. ``mkdir -p`` on already-present
        directories is a no-op, so re-running this is safe.
        """
        if self.pre_baked_agent_id is None:
            raise RuntimeError(
                "ImbueCloudHost.create_agent_state requires pre_baked_agent_id; "
                "this host was constructed outside the lease flow."
            )
        if options.agent_id is not None and options.agent_id != self.pre_baked_agent_id:
            raise ValueError(
                f"imbue_cloud agent id is fixed by the lease ({self.pre_baked_agent_id}); "
                f"caller requested {options.agent_id}. Drop --id to let the lease decide."
            )
        if options.agent_id != self.pre_baked_agent_id:
            options = options.model_copy(update={"agent_id": self.pre_baked_agent_id})
        return super().create_agent_state(work_dir_path, options, created_branch_name)

    def provision_agent(
        self,
        agent: AgentInterface,
        options: CreateAgentOptions,
        mngr_ctx: MngrContext,
    ) -> None:
        """Pool hosts are already fully provisioned; only update the agent env file.

        Standard ``Host.provision_agent`` would re-run package install, file
        transfers, and agent-type provisioning -- all of which the pool baking
        step already did. We just need the agent env file to reflect the
        caller's ``--env`` flags (and the caller-renamed ``MNGR_AGENT_NAME``)
        and, when an ``ANTHROPIC_API_KEY`` lands anywhere in the env (host or
        agent), the claude config patch that lets ``claude`` accept the
        LiteLLM key. ``--pass-host-env ANTHROPIC_API_KEY`` (the minds path)
        writes to ``/mngr/env`` via ``set_env_vars``; ``--env
        ANTHROPIC_API_KEY=...`` writes to the per-agent env. We look at
        both, agent first so a per-agent override wins.
        """
        agent_env = self._collect_agent_env_vars(agent, options)
        self._write_agent_env_file(agent, agent_env)
        anthropic_api_key = agent_env.get("ANTHROPIC_API_KEY") or self.get_env_vars().get("ANTHROPIC_API_KEY")
        if anthropic_api_key:
            patch_command = _build_patch_claude_config_command(anthropic_api_key, agent.id)
            result = self.execute_idempotent_command(patch_command)
            if not result.success:
                raise RuntimeError(f"Failed to patch claude config on imbue_cloud host {self.id}: {result.stderr}")


def build_combined_inject_command(
    agent_id: AgentId,
    agent_env_path: str,
    host_env_path: str,
    minds_api_key: str | None,
    anthropic_api_key: str | None,
    anthropic_base_url: str | None,
    mngr_prefix: str | None,
    extra_env: Mapping[str, str] | None = None,
) -> str | None:
    """Build the single bash command that injects credentials into a leased agent.

    Mirrors the consolidated approach in ``apps/minds/imbue/minds/desktop_client/
    agent_creator.py`` (commit b65f52ac4): all writes are joined with ``&&`` so a
    single SSH round trip is sufficient and partial-failure leaves no
    half-injected state.

    Returns None when there is nothing to inject (caller should skip the exec).
    """
    pieces: list[str] = []

    if minds_api_key is not None:
        pieces.append(_sed_replace_env_line(agent_env_path, "MINDS_API_KEY", minds_api_key))

    if anthropic_api_key is not None:
        pieces.append(_sed_replace_env_line(host_env_path, "ANTHROPIC_API_KEY", anthropic_api_key))

    if anthropic_base_url is not None:
        pieces.append(_sed_replace_env_line(host_env_path, "ANTHROPIC_BASE_URL", anthropic_base_url))

    if anthropic_api_key is not None:
        pieces.append(_build_patch_claude_config_command(anthropic_api_key, agent_id))

    if mngr_prefix is not None:
        pieces.append(_sed_replace_env_line(host_env_path, "MNGR_PREFIX", mngr_prefix))

    if extra_env:
        for key, value in extra_env.items():
            pieces.append(_sed_replace_env_line(host_env_path, key, value))

    if not pieces:
        return None
    return " && ".join(pieces)


def _sed_replace_env_line(path: str, var_name: str, value: str) -> str:
    """Build a sed+echo expression that replaces ``KEY=...`` in an env file.

    Uses sed -i to delete any prior occurrence of the var, then appends a fresh
    KEY=VALUE line. The value is single-quoted in the echo, but for safety we
    escape embedded single quotes using the standard ``'\\''`` trick.
    """
    safe_value = value.replace("'", "'\\''")
    return f"sed -i '/^{var_name}=/d' {path} && echo '{var_name}={safe_value}' >> {path}"


def _build_patch_claude_config_command(litellm_key: str, agent_id: AgentId) -> str:
    """Build a python one-liner that patches the agent's claude config to approve the new key.

    Mirrors ``_build_patch_claude_config_command`` in minds' agent_creator.py.
    """
    claude_config_path = f"/mngr/agents/{agent_id}/plugin/claude/anthropic/.claude.json"
    key_suffix = litellm_key[-20:]
    return (
        'python3 -c "'
        "import json; "
        f"p='{claude_config_path}'; "
        "d=json.load(open(p)); "
        f"d['primaryApiKey']='{litellm_key}'; "
        "a=d.setdefault('customApiKeyResponses',{}).setdefault('approved',[]); "
        f"s='{key_suffix}'; "
        "a.append(s) if s not in a else None; "
        "d['customApiKeyResponses']['rejected']=[]; "
        "json.dump(d,open(p,'w'),indent=2)"
        '"'
    )


def _ensure_no_quote_chars(value: str, field_name: str) -> str:
    """Defensive guard so injected values can't break out of the sed/echo quoting.

    Raises ValueError if the value contains characters that we don't escape.
    """
    if any(c in value for c in ("\n", "\r", "\x00")):
        raise ValueError(f"{field_name} cannot contain newlines or null bytes: {value!r}")
    return value


def normalize_inject_args(
    minds_api_key: str | None,
    anthropic_api_key: str | None,
    anthropic_base_url: str | None,
    mngr_prefix: str | None,
    extra_env: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Validate and clean inject arguments before they are interpolated into bash.

    Centralized here so the claim CLI and any future caller share the same checks.
    """
    cleaned_extra: dict[str, str] = {}
    if extra_env:
        for key, value in extra_env.items():
            if not key or "=" in key:
                raise ValueError(f"Invalid env var name: {key!r}")
            cleaned_extra[key] = _ensure_no_quote_chars(value, f"env[{key}]")
    return {
        "minds_api_key": _ensure_no_quote_chars(minds_api_key, "MINDS_API_KEY") if minds_api_key else None,
        "anthropic_api_key": _ensure_no_quote_chars(anthropic_api_key, "ANTHROPIC_API_KEY")
        if anthropic_api_key
        else None,
        "anthropic_base_url": _ensure_no_quote_chars(anthropic_base_url, "ANTHROPIC_BASE_URL")
        if anthropic_base_url
        else None,
        "mngr_prefix": _ensure_no_quote_chars(mngr_prefix, "MNGR_PREFIX") if mngr_prefix else None,
        "extra_env": cleaned_extra or None,
    }


def host_label_for_agent(agent_name: AgentName) -> str:
    """Default host name suffix for an agent (matches today's minds convention)."""
    return f"{agent_name}-host"
