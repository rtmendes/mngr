# VPS Docker Provider -- Detailed Spec

## Motivation

mngr currently supports three provider backends for running agents:

- **local**: Agents run directly on the user's machine. No isolation, no remote access.
- **docker**: Agents run in Docker containers on the user's machine (or a Docker host reachable via `DOCKER_HOST`). Good isolation, but the user must have Docker running locally or manage their own Docker host.
- **modal**: Agents run in Modal cloud sandboxes. Great isolation and zero infrastructure management, but only works with Modal (a specific managed service), and Modal is not available in all regions and doesn't support all hardware configurations.

There is a large gap between "run Docker locally" and "use Modal". Many users have access to VPS providers (Vultr, DigitalOcean, Hetzner, Linode, AWS Lightsail, etc.) and want to run agents on cheap cloud VMs without being locked into Modal. They want the isolation benefits of Docker containers but on infrastructure they control.

The goal of this project is to create a generic VPS Docker provider layer that provisions a VPS from any cloud provider, installs Docker on it, and runs agents inside Docker containers on that VPS. The VPS is accessed purely via SSH, and the Docker containers inside are accessed via ProxyJump through the VPS. This gives users Modal-like convenience (one command to create remote agents) on any VPS provider.

We start with **Vultr** as the first concrete implementation because it has a simple API and cheap instances, but the abstraction layer is designed so that adding DigitalOcean, Hetzner, etc. is just implementing a small set of abstract methods.

### Two modes of operation

Different use cases call for different lifecycle models:

1. **Always-on VPS** (`vultr-always-on`): The VPS stays running; the Docker container is the "host" from mngr's perspective. Stopping the host stops the container; the VPS keeps running. This is good for users who want a persistent VPS that multiple agents share over time, or who want fast container start/stop without waiting for VPS boot.

2. **Ephemeral VPS** (`vultr-ephemeral`): The VPS *is* the host. Stopping the host halts the VPS (which preserves disk state but stops billing for compute). Starting the host boots the VPS back up. This is good for users who want to minimize cost -- they pay only when agents are actively running.

## Architecture

```
User Machine                              VPS (Vultr/DO/Hetzner/...)
+------------------+                      +-------------------------------+
|                  |   SSH (port 22)      |  VPS OS (Debian/Ubuntu)       |
|  mngr CLI        | ------------------> |                               |
|                  |                      |  Docker Engine                |
|  ~/.mngr/        |                      |  +-------------------------+ |
|    profile/      |   SSH ProxyJump      |  | Container (sshd)        | |
|      providers/  | - - - - - - - - - -> |  |                         | |
|        vultr/    |   via VPS:22 to      |  |  /mngr/ (host_dir)     | |
|          keys/   |   container:2222     |  |    agents/              | |
|                  |                      |  |    activity/            | |
+------------------+                      |  |    commands/            | |
                                          |  +-------------------------+ |
                                          |                               |
                                          |  Docker named volume          |
                                          |  (persistent host_dir data)   |
                                          +-------------------------------+
```

Key architectural decisions:

- **1:1 mapping**: Each VPS runs exactly one Docker container. This simplifies lifecycle management and avoids cross-container interference. If a user wants multiple agents, they share the same container (same as Docker provider).
- **SSH host keys injected at creation**: SSH host keys are generated locally and injected into the VPS via cloud-init `user_data`. The public key is added to local `known_hosts` immediately. No TOFU (trust-on-first-use) needed.
- **Docker commands over SSH**: All Docker commands on the VPS are executed via SSH (`ssh user@vps docker ...`), not via Docker SDK remote host. This keeps the attack surface minimal and reuses the same SSH connection we already have.
- **ProxyJump for container access**: Once the container is running sshd, mngr connects to it via `ssh -J user@vps root@localhost -p 2222`. The container's sshd port (2222) is only exposed on the VPS's loopback, not to the internet.
- **State volume**: Same pattern as the existing Docker provider -- a Docker named volume on the VPS stores host_dir data, making it persistent across container stop/start cycles.

## Package Structure

Two new packages:

```
libs/mngr_vps_docker/                    # Base classes + shared infrastructure
  pyproject.toml
  imbue/mngr_vps_docker/
    __init__.py                          # hookimpl marker
    config.py                            # VpsDockerProviderConfig
    errors.py                            # VpsDockerError hierarchy
    primitives.py                        # VPS-specific primitives (VpsInstanceId, etc.)
    vps_client.py                        # Abstract VpsClientInterface
    instance.py                          # AlwaysOnVpsDockerProvider, EphemeralVpsDockerProvider
    host_store.py                        # HostRecord, VpsDockerHostStore (reuses DockerHostStore pattern)
    docker_over_ssh.py                   # Run Docker commands on the VPS via SSH
    cloud_init.py                        # Generate cloud-init user_data scripts
    testing.py                           # Test utilities

libs/mngr_vultr/                         # Vultr-specific implementation
  pyproject.toml
  imbue/mngr_vultr/
    __init__.py                          # hookimpl marker
    config.py                            # VultrProviderConfig
    backend.py                           # Plugin registration (two backends)
    client.py                            # VultrVpsClient (implements VpsClientInterface)
    testing.py                           # Test utilities
```

### Dependency relationships

```
mngr_vultr -> mngr_vps_docker -> mngr (core)
                                  ^
                                  |
                          (reuses providers/ssh_utils,
                           providers/ssh_host_setup,
                           providers/base_provider)
```

Both packages register via pluggy entry points, following the same pattern as `mngr_modal`.

## VPS Client Interface

The core abstraction that concrete VPS providers implement. This is a pure API client -- no Docker, SSH setup, or mngr-specific logic.

```python
class VpsClientInterface(MutableModel, ABC):
    """Abstract interface for VPS provider API operations."""

    @abstractmethod
    def create_instance(
        self,
        label: str,
        region: str,
        plan: str,
        os_id: int,
        user_data: str,
        ssh_key_ids: Sequence[str],
        tags: Mapping[str, str],
    ) -> VpsInstanceId:
        """Provision a new VPS instance. Returns the instance ID."""
        ...

    @abstractmethod
    def destroy_instance(self, instance_id: VpsInstanceId) -> None:
        """Permanently destroy a VPS instance."""
        ...

    @abstractmethod
    def halt_instance(self, instance_id: VpsInstanceId) -> None:
        """Halt (power off) a VPS instance, preserving disk state."""
        ...

    @abstractmethod
    def start_instance(self, instance_id: VpsInstanceId) -> None:
        """Start (power on) a halted VPS instance."""
        ...

    @abstractmethod
    def get_instance_status(self, instance_id: VpsInstanceId) -> VpsInstanceStatus:
        """Get the current status of a VPS instance."""
        ...

    @abstractmethod
    def get_instance_ip(self, instance_id: VpsInstanceId) -> str:
        """Get the main IPv4 address of a VPS instance."""
        ...

    @abstractmethod
    def wait_for_instance_active(
        self, instance_id: VpsInstanceId, timeout_seconds: float = 300.0
    ) -> str:
        """Poll until instance is active and return its IP address."""
        ...

    @abstractmethod
    def create_snapshot(self, instance_id: VpsInstanceId, description: str) -> VpsSnapshotId:
        """Create a snapshot of the instance's disk."""
        ...

    @abstractmethod
    def delete_snapshot(self, snapshot_id: VpsSnapshotId) -> None:
        """Delete a snapshot."""
        ...

    @abstractmethod
    def list_snapshots(self) -> list[VpsSnapshotInfo]:
        """List all snapshots owned by this account."""
        ...

    @abstractmethod
    def upload_ssh_key(self, name: str, public_key: str) -> str:
        """Upload an SSH public key. Returns the key ID."""
        ...

    @abstractmethod
    def delete_ssh_key(self, key_id: str) -> None:
        """Delete an SSH key by its ID."""
        ...

    @abstractmethod
    def list_ssh_keys(self) -> list[VpsSshKeyInfo]:
        """List all SSH keys on the account."""
        ...
```

The interface is deliberately minimal. Each method maps to a single API call. The VPS Docker provider layer (in `instance.py`) composes these into higher-level operations (create VPS, wait for it, install Docker, run container, etc.).

### VPS Instance Status

```python
class VpsInstanceStatus(UpperCaseStrEnum):
    """Status of a VPS instance as reported by the provider API."""

    PENDING = auto()     # Being provisioned
    ACTIVE = auto()      # Running
    HALTED = auto()      # Powered off, disk preserved
    DESTROYING = auto()  # Being deleted
    UNKNOWN = auto()     # Unrecognized status
```

## Cloud-Init and VPS Provisioning

When a VPS is created, we pass a cloud-init `user_data` script that:

1. **Injects the SSH host key**: We generate an Ed25519 host keypair locally and embed the private key in the cloud-init script. This means we know the host key before the VPS boots, so we can add it to `known_hosts` immediately -- no TOFU prompts.
2. **Disables password authentication**: Ensures only key-based SSH access.
3. **Installs Docker**: Runs the official Docker install script (`get.docker.com`).
4. **Signals readiness**: Creates a marker file (`/var/run/mngr-ready`) after Docker is installed.

```yaml
#cloud-config
ssh_deletekeys: true
ssh_keys:
  ed25519_private: |
    <generated-private-key>
  ed25519_public: <generated-public-key>
runcmd:
  - apt-get update -qq
  - apt-get install -y -qq curl ca-certificates
  - curl -fsSL https://get.docker.com | sh
  - touch /var/run/mngr-ready
```

The SSH *client* key (for mngr to authenticate to the VPS) is uploaded to the VPS provider's SSH key store and referenced by ID in the create call. This is more reliable than injecting it via cloud-init, because the provider ensures the key is in `authorized_keys` even before cloud-init runs.

### VPS SSH Key Lifecycle

```
1. mngr generates RSA keypair locally (or loads existing one)
2. mngr uploads public key to Vultr SSH key store -> gets key_id
3. mngr creates VPS with ssh_key_ids=[key_id]
4. Vultr injects public key into root's authorized_keys
5. mngr can SSH into VPS immediately after boot
6. On destroy, mngr deletes the SSH key from Vultr
```

The SSH keys are stored at `~/.mngr/profile/providers/vultr/<instance_name>/keys/`:
- `vps_ssh_key` / `vps_ssh_key.pub` -- For authenticating to the VPS itself
- `container_ssh_key` / `container_ssh_key.pub` -- For authenticating to the Docker container (separate key for defense in depth)
- `host_key` / `host_key.pub` -- Ed25519 host key injected into VPS via cloud-init
- `container_host_key` / `container_host_key.pub` -- Ed25519 host key for the container's sshd
- `vps_known_hosts` -- Known hosts file for VPS connections
- `container_known_hosts` -- Known hosts file for container connections

### Known Hosts Management

When a VPS is created:
1. Generate host keypair locally
2. Inject private key into VPS via cloud-init `ssh_keys`
3. Add `<vps-ip> <host-public-key>` to `vps_known_hosts`

When a VPS IP changes (e.g., after halt/start on ephemeral):
1. Remove old entry from `vps_known_hosts`
2. Add new entry with new IP but same host key (the key is baked into the VPS disk)

When a VPS is destroyed:
1. Remove entry from `vps_known_hosts`

The container gets its own known_hosts file (`container_known_hosts`) with an entry for `[localhost]:2222 <container-host-public-key>`. Since we always ProxyJump through the VPS, the "hostname" in known_hosts is always `localhost`.

## Docker Over SSH

All Docker commands on the VPS are executed by running `ssh user@vps docker <command>`. This module provides helpers for common operations:

```python
class DockerOverSsh:
    """Execute Docker commands on a remote VPS via SSH."""

    def __init__(
        self,
        vps_ip: str,
        ssh_user: str,
        ssh_key_path: Path,
        known_hosts_path: Path,
    ) -> None: ...

    def run(self, docker_args: Sequence[str], timeout_seconds: float = 60.0) -> str:
        """Run a docker command on the VPS and return stdout."""
        ...

    def run_container(
        self,
        image: str,
        name: str,
        ports: Mapping[int, int],
        volumes: Sequence[str],
        labels: Mapping[str, str],
        extra_args: Sequence[str],
        entrypoint_cmd: str,
    ) -> str:
        """Run a detached container. Returns container ID."""
        ...

    def stop_container(self, container_id_or_name: str, timeout_seconds: int = 10) -> None: ...
    def start_container(self, container_id_or_name: str) -> None: ...
    def remove_container(self, container_id_or_name: str, force: bool = False) -> None: ...
    def exec_in_container(self, container_id_or_name: str, command: str) -> str: ...
    def commit_container(self, container_id_or_name: str, image_name: str) -> str: ...
    def inspect_container(self, container_id_or_name: str) -> dict: ...
    def list_containers(self, labels: Mapping[str, str] | None = None) -> list[dict]: ...
    def pull_image(self, image: str) -> None: ...
    def build_image(self, tag: str, build_args: Sequence[str]) -> None: ...
    def create_volume(self, name: str) -> None: ...
    def remove_volume(self, name: str) -> None: ...
    def volume_exists(self, name: str) -> bool: ...
```

Each method constructs an SSH command like:
```bash
ssh -i <key> -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=yes root@<vps-ip> docker <args>
```

The SSH connection uses `StrictHostKeyChecking=yes` because we pre-populate known_hosts.

## Container Setup

After the VPS is ready and Docker is installed, the provider:

1. **Creates a Docker named volume** on the VPS: `mngr-host-vol-<host_id_hex>`
2. **Pulls or builds the base image** (default: `debian:bookworm-slim`, or user-specified)
3. **Runs the container** with:
   - Port 2222 mapped to the VPS's localhost only (`-p 127.0.0.1:2222:22`)
   - The named volume mounted at `/mngr-vol`
   - Labels for discovery (`com.imbue.mngr.host-id`, etc.)
   - The container entrypoint: `trap 'exit 0' TERM; tail -f /dev/null & wait`
   - Any user-specified start_args
4. **Sets up SSH in the container** (via `docker exec`):
   - Installs required packages (openssh-server, tmux, curl, rsync, git, jq, etc.) using `build_check_and_install_packages_command` from `ssh_host_setup`
   - Configures SSH keys (container client key, container host key)
   - Symlinks `/mngr` to `/mngr-vol` (the volume mount point)
   - Starts sshd: `/usr/sbin/sshd -D -o MaxSessions=100 -p 22`
5. **Waits for container sshd** to be ready (via `wait_for_sshd` through the ProxyJump)
6. **Creates a pyinfra Host** with ProxyJump configuration
7. **Starts the activity watcher** and creates the shutdown script

### ProxyJump SSH Configuration

To reach the container, mngr uses SSH ProxyJump:

```
ssh -J root@<vps-ip> -i <container_key> -p 2222 -o UserKnownHostsFile=<container_known_hosts> root@localhost
```

The pyinfra Host is created with these SSH settings:
```python
host_data = {
    "ssh_user": "root",
    "ssh_port": 2222,
    "ssh_key": str(container_key_path),
    "ssh_known_hosts_file": str(container_known_hosts_path),
    "ssh_strict_host_key_checking": "yes",
    "ssh_proxy_command": f"ssh -i {vps_key_path} -o UserKnownHostsFile={vps_known_hosts_path} -o StrictHostKeyChecking=yes -W localhost:2222 root@{vps_ip}",
}
```

## AlwaysOnVpsDockerProvider

In this mode, the VPS is a long-lived server. The Docker container is the mngr "host".

### Lifecycle

| mngr operation | What happens |
|---|---|
| `create_host` | Provision VPS (if needed), install Docker, run container, setup SSH |
| `stop_host` | `docker stop` the container on the VPS. VPS keeps running. |
| `start_host` | `docker start` the container. Re-setup SSH if needed. |
| `destroy_host` | `docker rm` the container. Delete volume. Optionally destroy VPS if no other containers. |
| idle timeout | `docker stop` the container. VPS keeps running. |

### VPS Reuse

For always-on mode, a single VPS can potentially be reused across multiple `create_host` calls. The VPS is identified by the provider instance name -- all hosts created under the same provider instance share the same VPS.

However, for the initial implementation, we maintain the 1:1 mapping (one VPS per host) for simplicity. VPS reuse can be added later.

### State Persistence

Host state is stored in two places:

1. **Docker named volume on VPS**: Contains the host_dir data (agents, activity, commands). Persists across container stop/start.
2. **Local host store**: A JSON file per host at `~/.mngr/profile/providers/vultr/<instance>/host_state/<host_id>.json`. Contains the HostRecord (VPS instance ID, VPS IP, container ID, SSH info, certified host data, snapshots).

The local host store is used for offline discovery (when the VPS or container is stopped). This is the same pattern as the Docker provider's DockerHostStore, but stored locally instead of on a Docker state volume.

### Snapshots

Snapshots use `docker commit` on the remote container (executed via SSH):

```bash
ssh root@<vps-ip> docker commit <container-id> mngr-snapshot-<host_id>-<timestamp>
```

The resulting image stays on the VPS's Docker image store. To restore from a snapshot, the old container is removed and a new one is created from the snapshot image (same pattern as Docker provider).

Snapshot images are local to the VPS. If the VPS is destroyed, snapshots are lost. This is an acceptable limitation for the always-on variant since snapshots are primarily for quick rollbacks, not for long-term backup.

## EphemeralVpsDockerProvider

In this mode, the VPS lifecycle *is* the host lifecycle. The VPS is created when the host is created, and halted when the host is stopped.

### Lifecycle

| mngr operation | What happens |
|---|---|
| `create_host` | Provision VPS, install Docker, run container, setup SSH |
| `stop_host` | `docker stop` container, then halt the VPS (preserves disk). |
| `start_host` | Start the VPS, wait for boot, `docker start` container, re-setup SSH. |
| `destroy_host` | Destroy the VPS instance (permanently deletes disk). |
| idle timeout | Same as `stop_host`. |

### IP Address Changes

When a VPS is halted and restarted, the IP address may change (depends on provider). The provider handles this by:

1. Querying the new IP from the provider API after start
2. Removing the old known_hosts entry
3. Adding a new known_hosts entry with the new IP (same host key -- the key is on the VPS's persistent disk)
4. Updating the HostRecord with the new IP

### Snapshots

Snapshots use the VPS provider's native snapshot API:

```python
vultr_client.create_snapshot(instance_id, description="mngr-snapshot-<name>")
```

This creates a full disk snapshot at the provider level. To restore, a new VPS is created from the snapshot image (the old VPS is destroyed first, then a new one is provisioned from the snapshot).

This is more expensive and slower than `docker commit`, but captures the entire state including the Docker daemon, volumes, and container.

### Cost Model

The ephemeral variant is designed to minimize cost:

- VPS is halted when idle (most providers don't charge for compute on halted instances, only for disk storage)
- On Vultr specifically: halted instances are still billed at the hourly rate. To truly stop billing, the instance must be destroyed and re-created from a snapshot. The ephemeral provider should support a `destroy_on_idle` option that destroys the VPS and creates a provider-level snapshot, then restores from that snapshot on next start.

**Important**: Vultr continues to bill for halted instances. The ephemeral variant's `halt` behavior saves no money on Vultr. The `destroy_on_idle` mode (destroy VPS + create snapshot) is the only way to truly stop billing. This should be the default behavior for the ephemeral Vultr provider. However, the base class should support both modes since other providers (e.g., DigitalOcean) do stop billing on halt.

## Configuration

### VpsDockerProviderConfig (base)

```python
class VpsDockerProviderConfig(ProviderInstanceConfig):
    """Base configuration for VPS Docker providers."""

    host_dir: Path = Field(
        default=Path("/mngr"),
        description="Base directory for mngr data inside containers",
    )
    default_image: str = Field(
        default="debian:bookworm-slim",
        description="Default Docker image for containers",
    )
    default_idle_timeout: int = Field(
        default=800,
        description="Default idle timeout in seconds",
    )
    default_idle_mode: IdleMode = Field(
        default=IdleMode.IO,
        description="Default idle detection mode",
    )
    default_activity_sources: tuple[ActivitySource, ...] = Field(
        default_factory=lambda: tuple(ActivitySource),
        description="Default activity sources",
    )
    ssh_connect_timeout: float = Field(
        default=60.0,
        description="Timeout for SSH connections in seconds",
    )
    vps_boot_timeout: float = Field(
        default=300.0,
        description="Timeout for VPS to become active after provisioning in seconds",
    )
    docker_install_timeout: float = Field(
        default=300.0,
        description="Timeout for Docker installation on the VPS in seconds",
    )
    container_ssh_port: int = Field(
        default=2222,
        description="Port for sshd inside the Docker container (mapped to VPS localhost)",
    )
    default_start_args: tuple[str, ...] = Field(
        default=(),
        description="Default docker run arguments applied to all containers",
    )
```

### VultrProviderConfig

```python
class VultrProviderConfig(VpsDockerProviderConfig):
    """Configuration for the Vultr VPS Docker provider."""

    backend: ProviderBackendName = Field(
        description="Provider backend ('vultr-always-on' or 'vultr-ephemeral')",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="Vultr API key. Falls back to VULTR_API_KEY env var.",
    )
    default_region: str = Field(
        default="ewr",
        description="Default Vultr region (e.g., 'ewr' for New Jersey)",
    )
    default_plan: str = Field(
        default="vc2-1c-1gb",
        description="Default Vultr plan (e.g., 'vc2-1c-1gb' for 1 CPU, 1GB RAM)",
    )
    default_os_id: int = Field(
        default=2136,
        description="Default Vultr OS ID (2136 = Debian 12 x64)",
    )
    is_destroy_on_idle: bool = Field(
        default=True,
        description=(
            "For ephemeral mode: destroy VPS and snapshot on idle instead of just halting. "
            "This is the only way to stop billing on Vultr."
        ),
    )
```

### Build Args

Build args control VPS provisioning and Docker image building. Parsed from the CLI `--build` flag, similar to how Modal parses build args:

```
--region=ewr          # Vultr region
--plan=vc2-2c-4gb     # Vultr plan (CPU/RAM)
--os=2136             # Vultr OS ID
--file=Dockerfile     # Build Docker image from Dockerfile
--image=ubuntu:22.04  # Use a specific Docker image
```

### Start Args

Start args are passed to `docker run` when creating the container:

```
--cpus=2              # CPU limit for container
--memory=4g           # Memory limit for container
-v /data:/data        # Extra volume mounts
--network host        # Network mode
```

These follow the same pattern as the Docker provider's start args.

## Host Records

Host records are stored locally at `~/.mngr/profile/providers/vultr/<instance>/host_state/<host_id>.json`:

```python
class VpsHostConfig(HostConfig):
    """VPS-specific host configuration stored in the host record."""

    vps_instance_id: VpsInstanceId = Field(description="Provider-specific VPS instance ID")
    region: str = Field(description="Region where the VPS was created")
    plan: str = Field(description="VPS plan (CPU/RAM specification)")
    os_id: int = Field(description="OS image ID used to create the VPS")
    start_args: tuple[str, ...] = Field(default=(), description="Docker run arguments for replay on snapshot restore")
    image: str | None = Field(default=None, description="Docker image used for the container")
    container_name: str = Field(description="Docker container name on the VPS")
    volume_name: str = Field(description="Docker volume name on the VPS")
    vps_ssh_key_id: str | None = Field(default=None, description="Vultr SSH key ID (for cleanup on destroy)")

class VpsDockerHostRecord(FrozenModel):
    """Host metadata stored locally for offline discovery."""

    certified_host_data: CertifiedHostData
    vps_ip: str | None = Field(default=None, description="Current IP address of the VPS")
    ssh_host_public_key: str | None = Field(default=None, description="VPS SSH host public key")
    container_ssh_host_public_key: str | None = Field(default=None, description="Container SSH host public key")
    config: VpsHostConfig | None = Field(default=None, description="VPS and container configuration")
```

The host store follows the same pattern as `DockerHostStore` -- a `MutableModel` with read/write/list/delete methods and an in-memory cache.

## Discovery and Listing

### Online hosts (VPS and container running)

1. Query VPS provider API for all instances with mngr labels/tags
2. For each running VPS, check if the container is running (via SSH to VPS)
3. If container is running, SSH into it (via ProxyJump) to read host data
4. Build HostDetails and AgentDetails as usual

### Offline hosts (VPS halted or container stopped)

1. Read local host store for all HostRecords
2. Cross-reference with VPS provider API to determine current VPS status
3. Build OfflineHost from certified data in the HostRecord

### Optimization

For listing, avoid SSH-ing into every container. Instead:
1. List all VPS instances from the provider API (single API call)
2. For running VPSes, batch-collect agent data via a single SSH command through the VPS
3. For stopped VPSes, use locally cached agent data from the host store

## Idle Detection and Shutdown

Idle detection works identically to the Docker provider:

1. Activity watcher runs inside the container, monitoring file mtimes in `host_dir/activity/`
2. When idle timeout is reached, the watcher calls `host_dir/commands/shutdown.sh`
3. The shutdown script's behavior differs by mode:

**Always-on**: `shutdown.sh` sends SIGTERM to PID 1 in the container, which causes the container to stop. The VPS keeps running.

**Ephemeral**: `shutdown.sh` sends SIGTERM to PID 1 in the container, then SSHes back to the VPS to halt it (or destroy it if `is_destroy_on_idle` is true). The shutdown script needs the VPS provider credentials and instance ID to do this, which are stored in a config file on the container.

For the ephemeral case, the shutdown script is more complex:

```bash
#!/bin/bash
# Stop the container (from inside -- kill PID 1)
# The VPS-level shutdown is handled by a systemd service on the VPS
# that monitors the container and halts/destroys when it exits.
kill -TERM 1
```

Rather than having the container reach back to the VPS provider API, a simpler approach: install a systemd service on the VPS that monitors the container and triggers halt/destroy when the container exits. This avoids putting API credentials inside the container.

```bash
# /etc/systemd/system/mngr-container-monitor.service
[Unit]
Description=Monitor mngr container and halt VPS when it exits
After=docker.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'docker wait <container-name> && shutdown -h now'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

For `is_destroy_on_idle`, the monitor service can't destroy the VPS from within itself. Instead, the shutdown script persists agent data to the host store (via the same pattern as Modal's shutdown function), and the VPS simply halts. A separate cleanup mechanism on the user's machine (or a cron job) can destroy halted VPSes and create snapshots. Alternatively, the activity watcher can call an HTTP endpoint on the user's machine. This needs more design -- see Open Questions.

## Plugin Registration

### Entry Points

```toml
# libs/mngr_vultr/pyproject.toml
[project.entry-points.mngr]
vultr = "imbue.mngr_vultr.backend"
```

### Backend Registration

```python
# libs/mngr_vultr/imbue/mngr_vultr/backend.py

@hookimpl
def register_provider_backend() -> tuple[
    tuple[type[ProviderBackendInterface], type[ProviderInstanceConfig]],
    ...
]:
    return (
        (VultrAlwaysOnBackend, VultrProviderConfig),
        (VultrEphemeralBackend, VultrProviderConfig),
    )
```

Wait -- the existing `register_provider_backend` hookspec returns a single `tuple[type, type] | None`. To register two backends from one plugin, we need either:

(a) Two separate hook implementations (one per backend), or
(b) Modify the hookspec to accept a list.

Since we don't want to modify the hookspec, we register via **two separate modules** with separate entry points:

```toml
[project.entry-points.mngr]
vultr-always-on = "imbue.mngr_vultr.always_on_backend"
vultr-ephemeral = "imbue.mngr_vultr.ephemeral_backend"
```

Or, we use a single entry point module that returns both:

Actually, looking at the hookspec more carefully -- pluggy's `firstresult=False` (the default) means all implementations are called and results are collected as a list. So we can have one module return one backend, and register two entry points. Each entry point module registers one backend.

Alternatively, if the hookspec is modified to return `tuple | list[tuple] | None`, both can be registered from one hook. But let's not modify the hookspec for now.

**Decision**: Use two entry points, one per backend variant. Each module has its own `register_provider_backend` hookimpl that returns one `(backend_class, config_class)` pair.

## Error Handling

```python
class VpsDockerError(MngrError):
    """Base error for VPS Docker provider operations."""

class VpsProvisioningError(VpsDockerError):
    """Failed to provision a VPS instance."""

class VpsConnectionError(VpsDockerError):
    """Failed to connect to the VPS via SSH."""

class DockerNotInstalledError(VpsDockerError):
    """Docker is not installed or not running on the VPS."""

class ContainerSetupError(VpsDockerError):
    """Failed to set up the Docker container."""

class VpsApiError(VpsDockerError):
    """Error from the VPS provider API."""
```

## Security Considerations

1. **SSH key isolation**: Each provider instance gets its own SSH keypair. The VPS key and container key are separate -- compromising the container key doesn't grant VPS-level access.
2. **Container port binding**: The container's sshd port (2222) is bound to `127.0.0.1` on the VPS, not `0.0.0.0`. It's only reachable via ProxyJump through the VPS.
3. **Cloud-init host keys**: SSH host keys are generated locally and injected via cloud-init. This prevents MITM attacks during initial connection.
4. **No API credentials in containers**: VPS provider API keys never enter the container. The container is treated as untrusted, same as Modal sandboxes.
5. **Firewall**: The VPS should have a firewall that only allows SSH (port 22) inbound. Docker's default bridge network provides container isolation.

## Process Lifecycle

### Host Creation (always-on mode)

1. Generate or load SSH keypairs (VPS client key, container client key, VPS host key, container host key)
2. Upload VPS client public key to Vultr API
3. Generate cloud-init user_data with VPS host key
4. Create VPS via Vultr API (region, plan, OS, user_data, ssh_key_id)
5. Wait for VPS to become active (poll API, timeout 300s)
6. Add VPS IP + host key to `vps_known_hosts`
7. Wait for cloud-init to complete (poll via SSH for `/var/run/mngr-ready`, timeout 300s)
8. Create Docker named volume on VPS (via `docker volume create` over SSH)
9. Pull or build Docker image on VPS
10. Run container with volume mount, port mapping, labels
11. Set up SSH in container (install packages, configure keys, start sshd) via `docker exec`
12. Add container host key to `container_known_hosts`
13. Wait for container sshd (via ProxyJump, timeout 60s)
14. Create pyinfra Host with ProxyJump config
15. Set up activity watcher and shutdown script
16. Write HostRecord to local host store
17. Return Host object

### Host Stop (always-on mode)

1. Optionally persist agent data to host store
2. `docker stop` the container on VPS (via SSH)
3. Update HostRecord with STOPPED state

### Host Start (always-on mode)

1. Read HostRecord from host store
2. `docker start` the container on VPS (via SSH)
3. Wait for container sshd
4. Re-create pyinfra Host
5. Return Host object

### Host Destroy (always-on mode)

1. `docker stop` and `docker rm` the container
2. `docker volume rm` the named volume
3. Optionally destroy the VPS (if no other containers)
4. Delete SSH key from Vultr API
5. Delete HostRecord from host store
6. Clean up local known_hosts entries

### Host Creation (ephemeral mode)

Same as always-on steps 1-17, plus:
- Install the container-monitor systemd service on the VPS

### Host Stop (ephemeral mode)

1. Persist agent data to host store
2. `docker stop` the container
3. Halt the VPS via API (or destroy + snapshot if `is_destroy_on_idle`)
4. Update HostRecord with STOPPED state (and new snapshot ID if destroyed)

### Host Start (ephemeral mode)

1. Read HostRecord from host store
2. Start the VPS via API (or create new VPS from snapshot if it was destroyed)
3. Wait for VPS to become active
4. Update known_hosts if IP changed
5. Wait for Docker daemon to be ready
6. `docker start` the container
7. Wait for container sshd
8. Re-create pyinfra Host
9. Update HostRecord with new VPS IP
10. Return Host object

## Capability Properties

Both variants:
- `supports_snapshots` = `True`
- `supports_shutdown_hosts` = `True`
- `supports_volumes` = `True`
- `supports_mutable_tags` = `False` (tags stored in host record, not on VPS)

## Changes to Existing Code

### No changes to mngr core

The VPS Docker provider is entirely in new packages (`mngr_vps_docker` and `mngr_vultr`). It reuses existing infrastructure from mngr core:

- `ssh_utils.py`: `generate_ssh_keypair()`, `generate_ed25519_host_keypair()`, `load_or_create_ssh_keypair()`, `load_or_create_host_keypair()`, `add_host_to_known_hosts()`, `wait_for_sshd()`, `create_pyinfra_host()`
- `ssh_host_setup.py`: `build_check_and_install_packages_command()`, `build_configure_ssh_command()`, `build_add_known_hosts_command()`, `build_add_authorized_keys_command()`, `build_start_activity_watcher_command()`
- `base_provider.py`: `BaseProviderInstance` base class
- `config/data_types.py`: `ProviderInstanceConfig`, `MngrContext`
- `interfaces/`: `ProviderBackendInterface`, `ProviderInstanceInterface`, `HostInterface`, `OnlineHostInterface`
- `hosts/host.py`: `Host` class
- `hosts/offline_host.py`: `OfflineHost` class
- `interfaces/data_types.py`: `CertifiedHostData`, `HostConfig`, `SnapshotRecord`, `HostLifecycleOptions`

### Docker provider code to potentially share

The Docker provider has some patterns that the VPS Docker provider will closely mirror:

- `DockerHostStore` -- The VPS Docker provider can either reuse this class directly (if we factor out the Volume dependency) or create a parallel implementation. Since the VPS Docker provider stores host records locally (not on a Docker volume), a separate implementation that reads/writes to the local filesystem is cleaner.
- `ContainerConfig` -- Similar to `VpsHostConfig` but with fewer fields. No code sharing needed.
- Container entrypoint pattern (`trap 'exit 0' TERM; tail -f /dev/null & wait`) -- Reuse as a constant.

## Open Questions

1. **Ephemeral destroy-on-idle**: When `is_destroy_on_idle` is true, the VPS needs to be destroyed and a snapshot created. The container's shutdown script can't do this (no API credentials). Options:
   - (a) Have the activity watcher notify the user's machine via a webhook, and mngr handles the destroy+snapshot locally. Requires mngr to be running.
   - (b) Run a lightweight agent on the VPS (outside the container) that has API credentials and handles destroy+snapshot. Simpler but puts credentials on the VPS.
   - (c) Just halt the VPS (not destroy) on idle, and have `mngr gc` or `mngr cleanup` handle the destroy+snapshot asynchronously. The user pays for the halted VPS until cleanup runs. This is the simplest approach.
   - **Recommendation**: Start with (c). The user runs `mngr gc` periodically (or we add a reminder). Future improvement: add a local daemon or cron job that handles this automatically.

2. **VPS reuse for always-on mode**: Should multiple hosts be able to share a single VPS? This would be more cost-effective but adds complexity (port management, resource contention, cleanup). **Recommendation**: Start with 1:1 mapping. Add VPS reuse as a future enhancement.

3. **Vultr billing for halted instances**: Vultr bills for halted instances at the hourly rate. This makes the simple halt-on-idle approach for ephemeral mode cost-ineffective. The destroy+snapshot approach is needed to truly stop billing, but it adds 2-5 minutes of latency on restart (VPS provisioning from snapshot). **Recommendation**: Default to destroy+snapshot for Vultr ephemeral. Document the tradeoff.

4. **Docker image caching across VPS recreations**: When an ephemeral VPS is destroyed and recreated from a snapshot, the Docker images are baked into the snapshot. But if the user changes their Dockerfile, the new VPS needs to rebuild. Should we cache Docker images somewhere external? **Recommendation**: No, for now. The snapshot captures everything. If the user changes their Dockerfile, they do a full create (which is already the expected flow).

5. **Startup script vs cloud-init for Docker installation**: Cloud-init is standardized but slow (sequential boot). Vultr also supports "startup scripts" which run earlier. **Recommendation**: Use cloud-init (`user_data`) for portability across VPS providers. The extra few seconds of boot time is acceptable.

6. **Host key for ephemeral VPS across destroy/recreate**: When an ephemeral VPS is destroyed and recreated from snapshot, the SSH host key is baked into the snapshot, so it persists. But if creating a *new* VPS (not from snapshot), we need to inject a new host key. Should we reuse the same host key across VPS recreations? **Recommendation**: Yes, reuse the same host key (stored locally in the keys directory). This way known_hosts only needs the IP updated, not the key.

7. **Should `mngr_vps_docker` have its own entry point, or only be used as a library by concrete implementations like `mngr_vultr`?** Since `mngr_vps_docker` provides abstract base classes, it shouldn't register any backends itself. It's a library, not a plugin. Only `mngr_vultr` (and future `mngr_digitalocean`, etc.) register entry points. **Recommendation**: `mngr_vps_docker` has no entry points. It's a dependency of `mngr_vultr`.
