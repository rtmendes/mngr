"""Host class for imbue_cloud-leased agents.

Subclasses mngr's Host to remember the pre-baked agent id so the claim
flow (rename + relabel + env injection) can target it directly.
"""

from typing import Any
from typing import Mapping

from pydantic import Field

from imbue.mngr.hosts.host import Host
from imbue.mngr.primitives import AgentId
from imbue.mngr.primitives import AgentName


class ImbueCloudHost(Host):
    """A leased pool host.

    The pre-baked agent's id is captured at lease time so the plugin's claim
    command can do its rename + label + env-injection sequence on the right
    agent. Outside the claim flow this field is informational.
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
