import socket
import threading
import time
from pathlib import Path

import pytest

from imbue.minds.desktop_client.latchkey_gateway import LatchkeyBinaryNotFoundError
from imbue.minds.desktop_client.latchkey_gateway import LatchkeyGatewayDestructionHandler
from imbue.minds.desktop_client.latchkey_gateway import LatchkeyGatewayDiscoveryHandler
from imbue.minds.desktop_client.latchkey_gateway import LatchkeyGatewayManager
from imbue.minds.desktop_client.latchkey_gateway import LatchkeyGatewayManagerNotStartedError
from imbue.minds.desktop_client.latchkey_gateway import is_local_reachable_provider
from imbue.mngr.primitives import AgentId


def test_is_local_reachable_provider_accepts_local_providers() -> None:
    assert is_local_reachable_provider("local")
    assert is_local_reachable_provider("docker")
    assert is_local_reachable_provider("lima")


def test_is_local_reachable_provider_rejects_vps_providers() -> None:
    assert not is_local_reachable_provider("modal")
    assert not is_local_reachable_provider("vultr")
    assert not is_local_reachable_provider("unknown")
    assert not is_local_reachable_provider("")


def test_ensure_gateway_started_requires_start() -> None:
    manager = LatchkeyGatewayManager()
    with pytest.raises(LatchkeyGatewayManagerNotStartedError):
        manager.ensure_gateway_started(AgentId())


def test_stop_is_idempotent_before_start() -> None:
    manager = LatchkeyGatewayManager()
    manager.stop()


def test_ensure_gateway_started_raises_when_binary_missing(tmp_path: Path) -> None:
    manager = LatchkeyGatewayManager(latchkey_binary=str(tmp_path / "definitely-does-not-exist"))
    manager.start()
    try:
        with pytest.raises(LatchkeyBinaryNotFoundError):
            manager.ensure_gateway_started(AgentId())
    finally:
        manager.stop()


def _make_fake_latchkey_binary(tmp_path: Path) -> Path:
    """Build a shell script that imitates ``latchkey gateway``.

    Binds a TCP socket on the host:port supplied via environment variables
    (matching the real binary's contract) and sleeps until terminated.
    The returned path is executable.
    """
    script = tmp_path / "fake-latchkey.sh"
    # signal.pause() blocks indefinitely until a signal arrives, letting the
    # script keep the port bound without busy-looping. SIGTERM triggers the
    # handler and exits cleanly.
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, socket, signal, sys\n"
        "host = os.environ['LATCHKEY_GATEWAY_LISTEN_HOST']\n"
        "port = int(os.environ['LATCHKEY_GATEWAY_LISTEN_PORT'])\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "sock.bind((host, port))\n"
        "sock.listen(1)\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "signal.pause()\n"
    )
    script.chmod(0o755)
    return script


_POLL_INTERVAL_SECONDS = 0.05


def _wait_for_listening(host: str, port: int, timeout: float = 5.0) -> bool:
    """Poll until something accepts TCP connections on host:port."""
    poll_event = threading.Event()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                poll_event.wait(timeout=_POLL_INTERVAL_SECONDS)
    return False


def test_ensure_gateway_started_spawns_subprocess_and_allocates_port(tmp_path: Path) -> None:
    fake_binary = _make_fake_latchkey_binary(tmp_path)
    manager = LatchkeyGatewayManager(latchkey_binary=str(fake_binary))
    manager.start()
    try:
        agent_id = AgentId()
        info = manager.ensure_gateway_started(agent_id)
        assert info.agent_id == agent_id
        assert info.host == "127.0.0.1"
        assert info.port > 0
        assert _wait_for_listening(info.host, info.port), "gateway did not start listening"

        # Idempotent: a second call returns the same info without spawning again.
        second = manager.ensure_gateway_started(agent_id)
        assert second == info
        assert len(manager.list_gateways()) == 1
    finally:
        manager.stop()


def test_stop_gateway_for_agent_terminates_subprocess(tmp_path: Path) -> None:
    fake_binary = _make_fake_latchkey_binary(tmp_path)
    manager = LatchkeyGatewayManager(latchkey_binary=str(fake_binary))
    manager.start()
    try:
        agent_id = AgentId()
        info = manager.ensure_gateway_started(agent_id)
        assert _wait_for_listening(info.host, info.port)

        manager.stop_gateway_for_agent(agent_id)
        assert manager.get_gateway_info(agent_id) is None
        assert manager.list_gateways() == ()

        # The port should become free shortly after termination. Poll with a
        # timeout instead of asserting immediately because the kernel may
        # hold onto the socket briefly.
        poll_event = threading.Event()
        deadline = time.monotonic() + 5.0
        reclaimed = False
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind((info.host, info.port))
                    reclaimed = True
                    break
                except OSError:
                    poll_event.wait(timeout=_POLL_INTERVAL_SECONDS)
        assert reclaimed, "gateway port did not become reclaimable after stop_gateway_for_agent"
    finally:
        manager.stop()


def test_stop_gateway_for_agent_is_no_op_when_not_running() -> None:
    manager = LatchkeyGatewayManager()
    manager.start()
    try:
        # No gateway has been started for this agent; stop should quietly succeed.
        manager.stop_gateway_for_agent(AgentId())
    finally:
        manager.stop()


def test_discovery_handler_skips_non_local_providers(tmp_path: Path) -> None:
    fake_binary = _make_fake_latchkey_binary(tmp_path)
    manager = LatchkeyGatewayManager(latchkey_binary=str(fake_binary))
    manager.start()
    try:
        handler = LatchkeyGatewayDiscoveryHandler(gateway_manager=manager)
        handler(AgentId(), None, "modal")
        handler(AgentId(), None, "vultr")
        assert manager.list_gateways() == ()
    finally:
        manager.stop()


def test_discovery_handler_spawns_for_local_providers(tmp_path: Path) -> None:
    fake_binary = _make_fake_latchkey_binary(tmp_path)
    manager = LatchkeyGatewayManager(latchkey_binary=str(fake_binary))
    manager.start()
    try:
        handler = LatchkeyGatewayDiscoveryHandler(gateway_manager=manager)
        local_agent = AgentId()
        docker_agent = AgentId()
        lima_agent = AgentId()
        handler(local_agent, None, "local")
        handler(docker_agent, None, "docker")
        handler(lima_agent, None, "lima")
        assert {info.agent_id for info in manager.list_gateways()} == {local_agent, docker_agent, lima_agent}
    finally:
        manager.stop()


def test_discovery_handler_swallows_gateway_errors(tmp_path: Path) -> None:
    """A missing binary must not crash the discovery callback -- just log a warning."""
    manager = LatchkeyGatewayManager(latchkey_binary=str(tmp_path / "missing"))
    manager.start()
    try:
        handler = LatchkeyGatewayDiscoveryHandler(gateway_manager=manager)
        handler(AgentId(), None, "local")
        assert manager.list_gateways() == ()
    finally:
        manager.stop()


def test_destruction_handler_stops_gateway(tmp_path: Path) -> None:
    fake_binary = _make_fake_latchkey_binary(tmp_path)
    manager = LatchkeyGatewayManager(latchkey_binary=str(fake_binary))
    manager.start()
    try:
        discovery = LatchkeyGatewayDiscoveryHandler(gateway_manager=manager)
        destruction = LatchkeyGatewayDestructionHandler(gateway_manager=manager)
        agent_id = AgentId()
        discovery(agent_id, None, "docker")
        assert manager.get_gateway_info(agent_id) is not None

        destruction(agent_id)
        assert manager.get_gateway_info(agent_id) is None
    finally:
        manager.stop()
