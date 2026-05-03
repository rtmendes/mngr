"""`mngr imbue_cloud claim ...` command.

Replaces today's minds-side LEASED flow. In one CLI invocation:
  1. Lease a matching pool host from the connector.
  2. Persist a per-host SSH keypair under providers/imbue_cloud/<instance>/hosts/<host_id>/.
  3. Wait for the leased container's sshd to accept connections.
  4. Build an ImbueCloudHost and call host.rename_agent(name, labels_to_merge=...) -- ONE
     atomic data.json write that lands the rename and label-merge together.
  5. Run a single &&-chained bash command via host.execute_command for env injection
     (MINDS_API_KEY, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, claude config patch,
     MNGR_PREFIX, plus any --env additions). One SSH round trip.
  6. Optionally start the agent.

The two-round-trip design matches the recently-merged minds optimization (see
commits 9eb5356a5 and b65f52ac4).
"""

import json as _json
import os
import time
from pathlib import Path
from typing import Final

import click
import paramiko
from loguru import logger

from imbue.mngr.errors import MngrError
from imbue.mngr.primitives import AgentId
from imbue.mngr.primitives import AgentName
from imbue.mngr.primitives import HostId
from imbue.mngr.providers.ssh_utils import add_host_to_known_hosts
from imbue.mngr.providers.ssh_utils import save_ssh_keypair
from imbue.mngr.providers.ssh_utils import wait_for_sshd
from imbue.mngr_imbue_cloud.auth_helper import get_active_token
from imbue.mngr_imbue_cloud.cli._common import emit_json
from imbue.mngr_imbue_cloud.cli._common import fail_with_json
from imbue.mngr_imbue_cloud.cli._common import get_default_host_dir
from imbue.mngr_imbue_cloud.cli._common import handle_imbue_cloud_errors
from imbue.mngr_imbue_cloud.cli._common import make_connector_client
from imbue.mngr_imbue_cloud.cli._common import make_session_store
from imbue.mngr_imbue_cloud.cli._common import parse_account
from imbue.mngr_imbue_cloud.config import get_provider_data_dir
from imbue.mngr_imbue_cloud.data_types import LeaseAttributes
from imbue.mngr_imbue_cloud.host import build_combined_inject_command
from imbue.mngr_imbue_cloud.host import normalize_inject_args
from imbue.mngr_imbue_cloud.primitives import ImbueCloudAccount
from imbue.mngr_imbue_cloud.primitives import slugify_account

_DEFAULT_INSTANCE_PREFIX: Final[str] = "imbue_cloud_"
_SSH_WAIT_TIMEOUT_SECONDS: Final[float] = 120.0


def _resolve_provider_state_dir(account: ImbueCloudAccount, instance_name_override: str | None) -> Path:
    instance_name = instance_name_override or f"{_DEFAULT_INSTANCE_PREFIX}{slugify_account(account)}"
    return get_provider_data_dir(get_default_host_dir(), instance_name)


def _scan_container_host_key(vps_ip: str, container_ssh_port: int) -> str | None:
    """Best-effort: pull the container's sshd public key for the known_hosts file.

    We talk to the leased container directly (vps_ip:container_ssh_port). If
    ``ssh-keyscan`` fails we fall back to leaving known_hosts empty and rely on
    the caller's ``--strict-host-key-checking=accept-new`` (or equivalent).
    """
    transport = paramiko.Transport((vps_ip, container_ssh_port))
    try:
        transport.start_client(timeout=10.0)
        host_key = transport.get_remote_server_key()
    except (paramiko.SSHException, OSError):
        return None
    finally:
        try:
            transport.close()
        except (OSError, paramiko.SSHException):
            pass
    key_type = host_key.get_name()
    key_b64 = host_key.get_base64()
    return f"{key_type} {key_b64}"


def _wait_for_agent_visible(host: object, agent_id: AgentId, timeout_seconds: float = 30.0) -> object | None:
    """Poll the host's discover_agents for the pre-baked agent.

    Returns the AgentInterface once visible, or None on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        agents = host.get_agents()  # type: ignore[attr-defined]
        for agent in agents:
            if str(agent.id) == str(agent_id):
                return agent
        time.sleep(2.0)
    return None


@click.command(name="claim")
@click.argument("agent_name")
@click.option("--account", required=True, help="Account email (must already be signed in)")
@click.option("--repo-url", default=None, help="Repo URL to constrain the lease (matched server-side)")
@click.option("--repo-branch-or-tag", default=None, help="Branch or tag to constrain the lease")
@click.option("--cpus", default=None, type=int, help="Required CPU count to constrain the lease")
@click.option("--memory-gb", default=None, type=int, help="Required memory in GB to constrain the lease")
@click.option("--gpu-count", default=None, type=int, help="Required GPU count to constrain the lease")
@click.option(
    "--label",
    "labels",
    multiple=True,
    metavar="KEY=VALUE",
    help="Labels to merge into the pre-baked agent's labels (repeatable).",
)
@click.option(
    "--env",
    "envs",
    multiple=True,
    metavar="KEY=VALUE",
    help="Extra env var to write into the leased agent's host env file (repeatable).",
)
@click.option("--minds-api-key", default=None, help="If set, write MINDS_API_KEY=<value> into the agent env")
@click.option("--anthropic-api-key", default=None, help="If set, write ANTHROPIC_API_KEY into the host env")
@click.option(
    "--anthropic-base-url",
    default=None,
    help="If set, write ANTHROPIC_BASE_URL into the host env (used together with --anthropic-api-key)",
)
@click.option(
    "--mngr-prefix",
    default=None,
    help=(
        "If set, write MNGR_PREFIX into the host env so services on the leased host see the "
        "correct mngr prefix. Defaults to whatever MNGR_PREFIX is set to in this process."
    ),
)
@click.option(
    "--start/--no-start",
    default=True,
    help="Start the agent once claim succeeds (default: start).",
)
@click.option(
    "--instance-name",
    default=None,
    help="Override the provider instance name (defaults to imbue_cloud_<account-slug>).",
)
@click.option("--connector-url", default=None, help="Override connector URL")
@handle_imbue_cloud_errors
def claim(
    agent_name: str,
    account: str,
    repo_url: str | None,
    repo_branch_or_tag: str | None,
    cpus: int | None,
    memory_gb: int | None,
    gpu_count: int | None,
    labels: tuple[str, ...],
    envs: tuple[str, ...],
    minds_api_key: str | None,
    anthropic_api_key: str | None,
    anthropic_base_url: str | None,
    mngr_prefix: str | None,
    start: bool,
    instance_name: str | None,
    connector_url: str | None,
) -> None:
    """Lease a host, claim its pre-baked agent under the requested name, and start it."""
    parsed_account = parse_account(account)
    label_map: dict[str, str] = {}
    for entry in labels:
        if "=" not in entry:
            fail_with_json(f"--label expects KEY=VALUE, got: {entry!r}", error_class="UsageError")
        key, value = entry.split("=", 1)
        if not key:
            fail_with_json(f"--label key cannot be empty: {entry!r}", error_class="UsageError")
        label_map[key] = value
    env_map: dict[str, str] = {}
    for entry in envs:
        if "=" not in entry:
            fail_with_json(f"--env expects KEY=VALUE, got: {entry!r}", error_class="UsageError")
        key, value = entry.split("=", 1)
        if not key:
            fail_with_json(f"--env key cannot be empty: {entry!r}", error_class="UsageError")
        env_map[key] = value

    if mngr_prefix is None:
        # Inherit from the calling shell so the leased agent's services use the same prefix.
        mngr_prefix = os.environ.get("MNGR_PREFIX") or None

    try:
        normalized = normalize_inject_args(
            minds_api_key=minds_api_key,
            anthropic_api_key=anthropic_api_key,
            anthropic_base_url=anthropic_base_url,
            mngr_prefix=mngr_prefix,
            extra_env=env_map or None,
        )
    except ValueError as exc:
        fail_with_json(str(exc), error_class="UsageError")

    try:
        parsed_agent_name = AgentName(agent_name)
    except ValueError as exc:
        fail_with_json(f"Invalid agent name: {exc}", error_class="UsageError")

    attributes = LeaseAttributes(
        repo_url=repo_url,
        repo_branch_or_tag=repo_branch_or_tag,
        cpus=cpus,
        memory_gb=memory_gb,
        gpu_count=gpu_count,
    )

    client = make_connector_client(connector_url)
    store = make_session_store()
    token = get_active_token(store, client, parsed_account)

    provider_dir = _resolve_provider_state_dir(parsed_account, instance_name)
    # Pre-generate a temporary keypair; we'll move it into the canonical
    # hosts/<host_id>/ location after the lease succeeds.
    tmp_key_dir = provider_dir / "leases" / f"pending-{int(time.time() * 1000)}"
    tmp_key_dir.mkdir(parents=True, exist_ok=True)
    private_key_path, public_key_path = save_ssh_keypair(tmp_key_dir, "ssh_key")
    public_key = public_key_path.read_text().strip()

    lease_result = client.lease_host(token, attributes, public_key)

    host_id = HostId(lease_result.host_id)
    pre_baked_agent_id = AgentId(lease_result.agent_id)
    final_host_dir = provider_dir / "hosts" / str(host_id)
    final_host_dir.mkdir(parents=True, exist_ok=True)
    final_private_key_path = final_host_dir / "ssh_key"
    final_public_key_path = final_host_dir / "ssh_key.pub"
    # Move the temp keypair into the canonical location.
    private_key_path.replace(final_private_key_path)
    public_key_path.replace(final_public_key_path)
    final_private_key_path.chmod(0o600)
    try:
        tmp_key_dir.rmdir()
        (provider_dir / "leases").rmdir()
    except OSError:
        pass

    # Persist a small lease metadata file so future commands can find host_db_id.
    lease_meta_path = final_host_dir / "lease.json"
    lease_meta_path.write_text(_json.dumps(lease_result.model_dump(), indent=2, default=str))

    # Wait for the container's sshd to be ready.
    try:
        wait_for_sshd(lease_result.vps_ip, lease_result.container_ssh_port, _SSH_WAIT_TIMEOUT_SECONDS)
    except MngrError as exc:
        fail_with_json(
            f"Container sshd not ready on {lease_result.vps_ip}:{lease_result.container_ssh_port}: {exc}",
            error_class="SSHTimeout",
            host_db_id=str(lease_result.host_db_id),
        )

    # Try to scan the container's host key so strict host-key checking succeeds.
    known_hosts_path = final_host_dir / "known_hosts"
    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    if not known_hosts_path.exists():
        known_hosts_path.touch()
    scanned_key = _scan_container_host_key(lease_result.vps_ip, lease_result.container_ssh_port)
    if scanned_key is not None:
        add_host_to_known_hosts(
            known_hosts_path,
            lease_result.vps_ip,
            lease_result.container_ssh_port,
            scanned_key,
        )

    # We don't go through the full mngr Host class here because constructing
    # one needs an MngrContext and a registered provider instance. Talking to
    # the leased container directly via paramiko keeps this command
    # self-contained and matches the architect spec's "minimal round trips"
    # guidance.
    _do_claim_via_paramiko(
        vps_ip=lease_result.vps_ip,
        container_ssh_port=lease_result.container_ssh_port,
        ssh_user=lease_result.ssh_user,
        private_key_path=final_private_key_path,
        agent_id=pre_baked_agent_id,
        new_agent_name=parsed_agent_name,
        labels_to_merge=label_map,
        normalized=normalized,
        host_id=host_id,
    )

    started: bool = False
    if start:
        started = _start_agent_via_ssh(
            vps_ip=lease_result.vps_ip,
            container_ssh_port=lease_result.container_ssh_port,
            ssh_user=lease_result.ssh_user,
            private_key_path=final_private_key_path,
            agent_id=pre_baked_agent_id,
            agent_name=parsed_agent_name,
        )

    emit_json(
        {
            "host_db_id": str(lease_result.host_db_id),
            "host_id": str(host_id),
            "agent_id": str(pre_baked_agent_id),
            "agent_name": str(parsed_agent_name),
            "vps_ip": lease_result.vps_ip,
            "container_ssh_port": lease_result.container_ssh_port,
            "ssh_user": lease_result.ssh_user,
            "private_key_path": str(final_private_key_path),
            "started": started,
        }
    )


def _do_claim_via_paramiko(
    vps_ip: str,
    container_ssh_port: int,
    ssh_user: str,
    private_key_path: Path,
    agent_id: AgentId,
    new_agent_name: AgentName,
    labels_to_merge: dict[str, str],
    normalized: dict,
    host_id: HostId,
) -> None:
    """Run the claim sequence (rename+labels + env injection) over paramiko.

    Two SSH commands total:
    - One python heredoc that atomically rewrites data.json and renames the tmux
      session in a single round trip.
    - One bash command that injects credentials/env vars in another round trip.
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = (
        paramiko.Ed25519Key.from_private_key_file(str(private_key_path))
        if _is_ed25519_key(private_key_path)
        else paramiko.RSAKey.from_private_key_file(str(private_key_path))
    )
    client.connect(
        hostname=vps_ip,
        port=container_ssh_port,
        username=ssh_user,
        pkey=pkey,
        timeout=15.0,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        # 1. Rename + label (single atomic data.json rewrite).
        rename_command = _build_rename_command(
            agent_id=agent_id,
            new_agent_name=new_agent_name,
            labels_to_merge=labels_to_merge,
        )
        _run_ssh_command_checked(client, rename_command, label="rename+label")

        # 2. Env injection (single &&-chained bash).
        env_command = build_combined_inject_command(
            agent_id=agent_id,
            agent_env_path=f"/mngr/agents/{agent_id}/env",
            host_env_path="/mngr/env",
            **normalized,
        )
        if env_command is not None:
            _run_ssh_command_checked(client, env_command, label="env-inject")
    finally:
        client.close()


def _start_agent_via_ssh(
    vps_ip: str,
    container_ssh_port: int,
    ssh_user: str,
    private_key_path: Path,
    agent_id: AgentId,
    agent_name: AgentName,
) -> bool:
    """Send the start command for the agent.

    This invokes ``mngr start <name>`` over SSH; mngr is expected to be on PATH
    inside the leased container (the pool image bakes it).
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = (
        paramiko.Ed25519Key.from_private_key_file(str(private_key_path))
        if _is_ed25519_key(private_key_path)
        else paramiko.RSAKey.from_private_key_file(str(private_key_path))
    )
    client.connect(
        hostname=vps_ip,
        port=container_ssh_port,
        username=ssh_user,
        pkey=pkey,
        timeout=15.0,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        cmd = f"mngr start {agent_name}"
        try:
            _run_ssh_command_checked(client, cmd, label="start")
            return True
        except RuntimeError as exc:
            logger.warning("mngr start failed inside leased container: {}", exc)
            return False
    finally:
        client.close()


def _run_ssh_command_checked(client: paramiko.SSHClient, command: str, *, label: str) -> None:
    """Run a command via paramiko and raise RuntimeError if it exits non-zero."""
    stdin, stdout, stderr = client.exec_command(command, timeout=180.0)
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode(errors="replace")
    out = stdout.read().decode(errors="replace")
    if exit_code != 0:
        raise RuntimeError(f"{label} command failed (exit {exit_code}): {err or out}")


def _is_ed25519_key(private_key_path: Path) -> bool:
    """Detect ed25519 vs RSA keys by reading the PEM header line."""
    try:
        with private_key_path.open("rb") as fh:
            head = fh.readline()
    except OSError:
        return False
    return b"OPENSSH" in head


def _build_rename_command(
    agent_id: AgentId,
    new_agent_name: AgentName,
    labels_to_merge: dict[str, str],
) -> str:
    """Build a python one-liner that atomically updates data.json and renames the tmux session.

    Mirrors the host-side OnlineHostInterface.rename_agent semantics but executes
    inline in a single SSH round trip:
      - Rename the tmux session if it exists under the old name
      - Update MNGR_AGENT_NAME in the agent env file
      - Atomically write data.json with new name + merged labels

    Stays defensive about quoting because the values pass through bash and python.
    """
    data_path = f"/mngr/agents/{agent_id}/data.json"
    env_path = f"/mngr/agents/{agent_id}/env"
    new_name_str = str(new_agent_name)
    labels_json = _json.dumps(labels_to_merge)
    # Inline python one-liner; keep the value strings safe by routing them
    # through json.dumps so quotes inside don't break things.
    return (
        "python3 - <<'PY_EOF'\n"
        "import json, os, shlex, subprocess\n"
        f"DATA = {_json.dumps(data_path)}\n"
        f"ENV = {_json.dumps(env_path)}\n"
        f"NEW_NAME = {_json.dumps(new_name_str)}\n"
        f"LABELS = {labels_json}\n"
        "with open(DATA) as f:\n"
        "    data = json.load(f)\n"
        "OLD_NAME = data.get('name', '')\n"
        "data['name'] = NEW_NAME\n"
        "if LABELS:\n"
        "    cur = data.get('labels') or {}\n"
        "    cur.update(LABELS)\n"
        "    data['labels'] = cur\n"
        "tmp = DATA + '.tmp'\n"
        "with open(tmp, 'w') as f:\n"
        "    json.dump(data, f, indent=2)\n"
        "os.replace(tmp, DATA)\n"
        "if OLD_NAME and OLD_NAME != NEW_NAME:\n"
        "    prefix = os.environ.get('MNGR_PREFIX', 'mngr-')\n"
        "    old_session = prefix + OLD_NAME\n"
        "    new_session = prefix + NEW_NAME\n"
        "    subprocess.run(\n"
        "        ['bash', '-c', f'tmux has-session -t =' + shlex.quote(old_session) + ' 2>/dev/null && tmux rename-session -t =' + shlex.quote(old_session) + ' ' + shlex.quote(new_session) + ' || true'],\n"
        "        check=False,\n"
        "    )\n"
        "if os.path.exists(ENV):\n"
        "    with open(ENV) as f:\n"
        "        lines = [l for l in f.read().splitlines() if not l.startswith('MNGR_AGENT_NAME=')]\n"
        "    lines.append(f'MNGR_AGENT_NAME={NEW_NAME}')\n"
        "    tmp_env = ENV + '.tmp'\n"
        "    with open(tmp_env, 'w') as f:\n"
        "        f.write('\\n'.join(lines) + '\\n')\n"
        "    os.replace(tmp_env, ENV)\n"
        "PY_EOF"
    )
