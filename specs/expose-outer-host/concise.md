# Expose outer host

## Overview

* Most container-based providers have a meaningful "outer" machine (the VPS, the local box, the SSH-reachable docker daemon host) that already has user-accessible SSH credentials, but each plugin reimplements one-off SSH paths to use it (`mngr_imbue_cloud/vps_admin.py`, `mngr_vps_docker/docker_over_ssh.py`).
* Add a single optional outer-host accessor (a context manager that yields `OnlineHostInterface | None`) on `OnlineHostInterface` and `ProviderInstanceInterface`. `None` means "no accessible outer" (Modal, `local`, `ssh`, docker-over-tcp).
* The outer host is a real `OnlineHostInterface` so file ops, `execute_command`, locking, and env vars all work directly. Methods that don't make sense for an outer host (agent CRUD, agent state, host-level lifecycle/state, snapshots, tags) raise `NotImplementedError` rather than returning garbage.
* Surface the abstraction via `mngr exec --outer`. Multiple targeted agents are deduped by outer host so the command runs once per unique outer; output is keyed by outer host with the input agents listed alongside.
* Delete the existing one-off SSH paths (`vps_admin.py`, `DockerOverSsh`, plus their plugin-specific error types) and route all callers through the new abstraction. This unlocks programmatic setup of sidecars / outer processes for any provider that exposes an outer host, without each consumer reimplementing SSH.

## Expected Behavior

### API

* `OnlineHostInterface.outer_host()` is a new context manager. `with host.outer_host() as outer:` yields either an `OnlineHostInterface` for the outer host or `None`. SSH connection (when applicable) is opened on `__enter__` and closed on `__exit__`. Each `with` entry produces a fresh outer-host instance and a fresh SSH connection — no caching across entries.
* `ProviderInstanceInterface.outer_host_for(host_id)` is the underlying entry point; the host-level method delegates to it. The provider method exists independently for paths (e.g. `mngr_imbue_cloud`'s destroy/start/stop) where only a `HostId` is in scope.
* `provider.outer_host_for(host_id)` raises `HostNotFoundError` for unknown ids. Outer-host construction is a pure function of (provider, host_id) and does not depend on the inner host being reachable.
* New capability flag `ProviderInstanceInterface.supports_outer_host: bool` indicates whether the provider can produce an outer host in principle (without actually constructing one). Defaults to `False`.

### Outer host's API surface

* Allowed (do what you'd expect): `execute_idempotent_command` / `execute_stateful_command`, `read_file` / `write_file` / `read_text_file` / `write_text_file`, `get_file_mtime`, `lock_cooperatively` / `is_lock_held` / `get_reported_lock_time`, env var getters/setters, `get_ssh_connection_info`, `get_name`, `disconnect`, `is_local`.
* Raises `NotImplementedError`: all agent CRUD (`create_agent_work_dir`, `create_agent_state`, `provision_agent`, `rename_agent`, `destroy_agent`, `start_agents`, `stop_agents`); agent discovery (`discover_agents`, `get_agents`); agent-state I/O (`host_dir`, `get_agent_env_path`, `save_agent_data`, `build_source_env_prefix`); idle/activity (`get_idle_seconds`, `get_reported_activity_time`, `record_activity`, `get_reported_activity_content`, `get_activity_config`, `set_activity_config`); certified data and reported plugin state files; lifecycle/state queries (`get_state`, `get_failure_reason`, `get_build_log`, `get_seconds_since_stopped`, `get_stop_time`, `get_boot_time`, `get_uptime_seconds`); `get_provider_resources`; snapshots; tags; `to_offline_host`.

### Per-provider behavior

* `local`: `outer_host_for` returns `None`; `supports_outer_host = False`.
* `ssh`: same.
* `mngr_modal`: same.
* `docker`: `supports_outer_host = True`. The outer host depends on the daemon URL:
    * Local socket (`""` or `unix://...`): outer = the local machine, constructed by reusing `LocalProviderInstance._create_local_pyinfra_host()`. The `local` provider does not need to be configured.
    * `ssh://user@host[:port]`: outer = the SSH-reachable VM. SSH credentials are resolved entirely by the user's `~/.ssh/config` + ssh-agent; mngr passes no key path.
    * `tcp://...`: returns `None`.
* `mngr_vps_docker` (and its subclass `mngr_vultr`): `supports_outer_host = True`. Outer = the VPS, accessed as `root@vps_ip:22` using the per-host private key already on disk in `providers/<name>/hosts/<host_id>/`.
* `mngr_imbue_cloud`: `supports_outer_host = True`. Outer = the leased VPS, accessed as `root@vps_ip:22` using the per-host private key already on disk.

### `mngr exec --outer`

* New `--outer` flag on `mngr exec`. When set, the command runs on the *outer host* of each targeted agent's host instead of on the agent's host.
* Targeted agents are grouped by their outer host using the canonical id `outer:<provider_instance_name>:<inner_host_id>`. The command executes **once per unique outer host**.
* Default cwd is the SSH user's home directory on the outer host. `--cwd` is honored if given.
* `--start/--no-start` is **ignored** in `--outer` mode: outer access does not depend on the inner host's lifecycle.
* Output rows are keyed by outer host (not agent). Each row carries:
    * `outer_host`: the canonical id `outer:<provider_instance_name>:<inner_host_id>`
    * `agents`: the list of input agent names whose outer host that was
    * `stdout`, `stderr`, `success` (as today)
* Existing `--on-error abort|continue` is unchanged and continues to govern runtime errors during the actual command execution.
* New tri-state `--missing-outer abort|warn|ignore` (default `warn`) governs behavior when one or more targeted agents have no accessible outer host:
    * `abort`: exit 1 immediately if any targeted agent has no outer host.
    * `warn`: skip those agents; emit one stderr `WARNING: agent <name> has no outer host (provider=<provider>)` per skipped agent.
    * `ignore`: silently skip.
* Skipped agents appear in a new structured field on the result: `MultiExecResult.skipped_agents: list[SkippedAgent]`, where `SkippedAgent` is a frozen pydantic model with `agent_id`, `agent_name`, `host_id`, `provider_name`, `reason`. Distinct from `failed_agents` (which remains for runtime errors).
* When *every* targeted agent has no outer host, `--missing-outer` is honored strictly: `abort` → exit 1; `warn` → warnings + exit 0 with no rows; `ignore` → silent exit 0.

### `mngr list`

* New `OUTER` column showing `yes`/`no` per agent, derived from `provider.supports_outer_host`. Hidden by default; opt-in via `--outer-host`.

### Migration of existing one-off SSH paths

* `mngr_imbue_cloud/vps_admin.py` is deleted. Its callers (`destroy_host`, `start_host`, `stop_host` in `ImbueCloudProvider`) move to `with self.outer_host_for(host_id) as outer: outer.execute_stateful_command("docker ...")`.
* `mngr_vps_docker/docker_over_ssh.py` and the `DockerOverSsh` class are deleted. Its callers move to the same outer-host pattern; image-build / container-run / container-exec / commit / inspect helpers become small private functions that wrap `outer.execute_stateful_command("docker ...")`.
* Plugin-specific error types are deleted: `ImbueCloudConnectorError`, `VpsConnectionError`, `ContainerSetupError`, `DockerNotReadyError`. `MngrError` / `HostConnectionError` propagate from outer-host operations instead.

## Changes

* `libs/mngr/imbue/mngr/interfaces/host.py`: add `OnlineHostInterface.outer_host()` context manager.
* `libs/mngr/imbue/mngr/interfaces/provider_instance.py`: add `outer_host_for(host_id)` context manager and `supports_outer_host: bool` capability; default base implementations return `None` / `False`.
* New `OuterHost(Host)` subclass that raises `NotImplementedError` for the methods listed under Expected Behavior; defines the canonical `outer:<provider_instance_name>:<inner_host_id>` id derivation.
* `libs/mngr/imbue/mngr/hosts/host.py`: implement `Host.outer_host()` to delegate to `self.provider_instance.outer_host_for(self.id)`.
* `libs/mngr/imbue/mngr/api/exec.py`: extend `MultiExecResult` with `skipped_agents: list[SkippedAgent]`; introduce group-by-outer-host execution.
* New `SkippedAgent` frozen pydantic model with `agent_id`, `agent_name`, `host_id`, `provider_name`, `reason`.
* `libs/mngr/imbue/mngr/cli/exec.py`: add `--outer` and `--missing-outer abort|warn|ignore` (default `warn`); ignore `--start/--no-start` in `--outer` mode; default cwd = SSH user's home on the outer; output rows keyed by outer-host canonical id with `agents` list.
* `libs/mngr/imbue/mngr/cli/list.py`: add `OUTER` column behind the `--outer-host` flag.
* `libs/mngr/imbue/mngr/providers/docker/instance.py`: implement `outer_host_for` (local socket → local pyinfra host via `LocalProviderInstance._create_local_pyinfra_host()`; `ssh://` → SSH pyinfra host with credentials from user's `~/.ssh/config` + ssh-agent; `tcp://` → `None`); set `supports_outer_host = True`.
* `libs/mngr/imbue/mngr/providers/local/instance.py`, `libs/mngr/imbue/mngr/providers/ssh/instance.py`: leave `outer_host_for` returning `None`; `supports_outer_host = False`.
* `libs/mngr_modal/`: same — `None` / `False`.
* `libs/mngr_vps_docker/`: implement `outer_host_for` (builds outer for `root@vps_ip:22` via the per-host SSH key on disk); `supports_outer_host = True`. Delete `docker_over_ssh.py` and its `DockerOverSsh` class; re-home its docker-CLI helpers as small private functions wrapping `outer.execute_stateful_command("docker ...")`. Delete `VpsConnectionError`, `ContainerSetupError`, `DockerNotReadyError`.
* `libs/mngr_vultr/`: nothing to add (inherits from `VpsDockerProvider`).
* `libs/mngr_imbue_cloud/`: implement `outer_host_for` (builds outer for `root@vps_ip:22` via the per-host SSH key on disk); `supports_outer_host = True`. Delete `vps_admin.py`; rewrite `destroy_host` / `start_host` / `stop_host` to use the new abstraction. Delete `ImbueCloudConnectorError`.
* Tests: unit coverage for `Host.outer_host()` delegation, `outer_host_for` returning `None` / raising `HostNotFoundError`, `OuterHost`'s `NotImplementedError` methods, `--missing-outer` per value, group-by-outer-host dedup, `MultiExecResult.skipped_agents` shape; integration test using a real local-docker container (outer = local machine); acceptance test for `mngr exec --outer` against a local-docker agent.
* Docs: update `libs/mngr/docs/concepts/hosts.md`, `libs/mngr/docs/commands/primary/exec.md`, and `libs/mngr/docs/commands/primary/list.md`.
