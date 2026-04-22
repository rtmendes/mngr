"""Per-agent Latchkey gateway processes for locally-reachable agents.

For each workspace agent running on the local machine or in a container/VM
on the local host (providers: ``local``, ``docker``, ``lima``), the desktop
client spawns a dedicated ``latchkey gateway`` subprocess bound to a free
port on 127.0.0.1. Cloud/VPS providers (``modal``, ``vultr``, ...) do not
get a gateway since agents there cannot reach the local machine directly.

Wiring the gateway's address into the agent's environment (so the agent
actually uses it) happens in a follow-up task.
"""

import os
import socket
import threading
from collections.abc import Mapping
from typing import Final

from loguru import logger
from pydantic import Field
from pydantic import PrivateAttr

from imbue.concurrency_group.concurrency_group import ConcurrencyGroup
from imbue.concurrency_group.concurrency_group import InvalidConcurrencyGroupStateError
from imbue.concurrency_group.errors import ProcessSetupError
from imbue.concurrency_group.local_process import RunningProcess
from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.logging import log_span
from imbue.imbue_common.mutable_model import MutableModel
from imbue.minds.desktop_client.ssh_tunnel import RemoteSSHInfo
from imbue.mngr.primitives import AgentId

LATCHKEY_BINARY: Final[str] = "latchkey"

_DEFAULT_LISTEN_HOST: Final[str] = "127.0.0.1"

# Providers whose agents run on the local machine or can easily reach it
# (containers and VMs on the same host). Cloud/VPS providers (``modal``,
# ``vultr``, ...) are excluded because agents there cannot reach 127.0.0.1
# on this machine.
_LOCAL_REACHABLE_PROVIDER_NAMES: Final[frozenset[str]] = frozenset({"local", "docker", "lima"})


class LatchkeyGatewayError(Exception):
    """Raised when a Latchkey gateway subprocess cannot be managed."""


class LatchkeyBinaryNotFoundError(LatchkeyGatewayError, FileNotFoundError):
    """Raised when the ``latchkey`` binary is not available on PATH."""


class LatchkeyGatewayManagerNotStartedError(LatchkeyGatewayError, RuntimeError):
    """Raised when the manager is used before ``start()`` has been called."""


class LatchkeyGatewayInfo(FrozenModel):
    """Metadata for a running per-agent Latchkey gateway."""

    agent_id: AgentId = Field(description="The agent this gateway is dedicated to")
    host: str = Field(description="Host the gateway is listening on (typically 127.0.0.1)")
    port: int = Field(description="Port the gateway is listening on")


def is_local_reachable_provider(provider_name: str) -> bool:
    """Return True iff agents on this provider can reach the local machine.

    Covers the local machine itself (``local``) and provider types that
    create containers or VMs on the local host (``docker``, ``lima``).
    Cloud/VPS providers (``modal``, ``vultr``, ...) are excluded.
    """
    return provider_name in _LOCAL_REACHABLE_PROVIDER_NAMES


def _allocate_free_port(host: str) -> int:
    """Pick a free TCP port on ``host`` by binding to port 0 and reading it back.

    There is an inherent TOCTOU race: the chosen port could be claimed by
    another process between the time this function returns and the time
    ``latchkey gateway`` rebinds it. In practice the window is tiny and
    the desktop client is the only interested party on 127.0.0.1. If it
    becomes a problem, switch to passing an already-bound socket into
    the subprocess via ``--fd``.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _build_gateway_env(base_env: Mapping[str, str], host: str, port: int) -> dict[str, str]:
    """Overlay ``LATCHKEY_GATEWAY_LISTEN_*`` onto a base environment."""
    merged = dict(base_env)
    merged["LATCHKEY_GATEWAY_LISTEN_HOST"] = host
    merged["LATCHKEY_GATEWAY_LISTEN_PORT"] = str(port)
    return merged


def _log_gateway_output(agent_id: AgentId, line: str, is_stdout: bool) -> None:
    stripped = line.rstrip("\n")
    if not stripped.strip():
        return
    if is_stdout:
        logger.debug("latchkey gateway [{}] stdout: {}", agent_id, stripped)
    else:
        logger.debug("latchkey gateway [{}] stderr: {}", agent_id, stripped)


class LatchkeyGatewayManager(MutableModel):
    """Spawns and tracks one ``latchkey gateway`` subprocess per local agent."""

    latchkey_binary: str = Field(default=LATCHKEY_BINARY, frozen=True, description="Path to latchkey binary")
    listen_host: str = Field(
        default=_DEFAULT_LISTEN_HOST,
        frozen=True,
        description="Host to bind each spawned gateway to",
    )

    _cg: ConcurrencyGroup = PrivateAttr(
        default_factory=lambda: ConcurrencyGroup(name="latchkey-gateway-manager"),
    )
    _processes: dict[str, RunningProcess] = PrivateAttr(default_factory=dict)
    _gateways: dict[str, LatchkeyGatewayInfo] = PrivateAttr(default_factory=dict)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _is_started: bool = PrivateAttr(default=False)

    def start(self) -> None:
        """Enter the underlying ConcurrencyGroup so subprocesses can be spawned."""
        with self._lock:
            if self._is_started:
                return
            self._cg.__enter__()
            self._is_started = True

    def stop(self) -> None:
        """Terminate all running gateways and release the ConcurrencyGroup."""
        with self._lock:
            if not self._is_started:
                return
            processes = list(self._processes.values())
            self._processes.clear()
            self._gateways.clear()
            self._is_started = False
        for process in processes:
            process.terminate()
        self._cg.__exit__(None, None, None)

    def ensure_gateway_started(self, agent_id: AgentId) -> LatchkeyGatewayInfo:
        """Start a gateway for ``agent_id`` if one is not already running.

        Idempotent: returns the existing ``LatchkeyGatewayInfo`` when the
        gateway subprocess for this agent is still alive, otherwise spawns
        a fresh one on a newly allocated free port.
        """
        aid_str = str(agent_id)
        with self._lock:
            if not self._is_started:
                raise LatchkeyGatewayManagerNotStartedError(
                    "LatchkeyGatewayManager.start() must be called before ensure_gateway_started()"
                )
            existing_info = self._gateways.get(aid_str)
            existing_process = self._processes.get(aid_str)
            if existing_info is not None and existing_process is not None and existing_process.returncode is None:
                return existing_info

            port = _allocate_free_port(self.listen_host)
            env = _build_gateway_env(os.environ, self.listen_host, port)
            command = [self.latchkey_binary, "gateway"]
            with log_span(
                "Starting latchkey gateway for agent {} on {}:{}",
                agent_id,
                self.listen_host,
                port,
            ):
                try:
                    process = self._cg.run_process_in_background(
                        command=command,
                        env=env,
                        on_output=lambda line, is_stdout: _log_gateway_output(agent_id, line, is_stdout),
                    )
                except ProcessSetupError as e:
                    # ConcurrencyGroup wraps Popen's FileNotFoundError into ProcessSetupError.
                    # Pick out the missing-binary case so callers can distinguish it from
                    # other kinds of setup failure (malformed env, etc.).
                    if isinstance(e.__cause__, FileNotFoundError):
                        raise LatchkeyBinaryNotFoundError(f"latchkey binary not found: {self.latchkey_binary}") from e
                    raise LatchkeyGatewayError(f"Failed to start latchkey gateway for agent {agent_id}: {e}") from e
                except InvalidConcurrencyGroupStateError as e:
                    raise LatchkeyGatewayManagerNotStartedError("LatchkeyGatewayManager is no longer active") from e
            info = LatchkeyGatewayInfo(agent_id=agent_id, host=self.listen_host, port=port)
            self._processes[aid_str] = process
            self._gateways[aid_str] = info
            return info

    def stop_gateway_for_agent(self, agent_id: AgentId) -> None:
        """Terminate the gateway for ``agent_id`` if one is running (no-op otherwise)."""
        aid_str = str(agent_id)
        with self._lock:
            process = self._processes.pop(aid_str, None)
            self._gateways.pop(aid_str, None)
        if process is None:
            return
        logger.info("Stopping latchkey gateway for agent {}", agent_id)
        process.terminate()

    def get_gateway_info(self, agent_id: AgentId) -> LatchkeyGatewayInfo | None:
        """Return the gateway info for ``agent_id``, or ``None`` if no gateway is running."""
        with self._lock:
            return self._gateways.get(str(agent_id))

    def list_gateways(self) -> tuple[LatchkeyGatewayInfo, ...]:
        """Return all currently tracked gateways."""
        with self._lock:
            return tuple(self._gateways.values())


class LatchkeyGatewayDiscoveryHandler(FrozenModel):
    """Discovery callback that spawns a Latchkey gateway for each local-reachable agent.

    Intended to be registered via ``MngrStreamManager.add_on_agent_discovered_callback``.
    Ignores agents whose provider is not local-reachable (cloud/VPS).
    """

    gateway_manager: LatchkeyGatewayManager = Field(description="Manager that owns the gateway subprocesses")

    def __call__(self, agent_id: AgentId, ssh_info: RemoteSSHInfo | None, provider_name: str) -> None:
        del ssh_info
        if not is_local_reachable_provider(provider_name):
            logger.trace(
                "Skipping latchkey gateway for agent {} on non-local provider {!r}",
                agent_id,
                provider_name,
            )
            return
        try:
            self.gateway_manager.ensure_gateway_started(agent_id)
        except LatchkeyGatewayError as e:
            logger.warning("Failed to start latchkey gateway for agent {}: {}", agent_id, e)


class LatchkeyGatewayDestructionHandler(FrozenModel):
    """Discovery callback that tears down the gateway when an agent is destroyed."""

    gateway_manager: LatchkeyGatewayManager = Field(description="Manager that owns the gateway subprocesses")

    def __call__(self, agent_id: AgentId) -> None:
        self.gateway_manager.stop_gateway_for_agent(agent_id)
