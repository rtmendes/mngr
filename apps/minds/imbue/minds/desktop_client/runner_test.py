import os
from pathlib import Path

from imbue.minds.desktop_client.runner import AgentDiscoveryHandler
from imbue.minds.desktop_client.runner import _build_cloudflare_client
from imbue.minds.desktop_client.ssh_tunnel import SSHTunnelManager
from imbue.mngr.primitives import AgentId


def test_agent_discovery_handler_writes_local_url_file(tmp_path: Path) -> None:
    """Verify local agents get a minds_api_url file written."""
    tunnel_manager = SSHTunnelManager()
    handler = AgentDiscoveryHandler(
        tunnel_manager=tunnel_manager,
        server_port=8420,
        mngr_host_dir=tmp_path,
    )

    agent_id = AgentId()

    # Call the handler with no SSH info (local agent)
    handler(agent_id, None)

    url_file = tmp_path / "agents" / str(agent_id) / "minds_api_url"
    assert url_file.exists(), "minds_api_url file was not written"
    assert url_file.read_text() == "http://127.0.0.1:8420"

    tunnel_manager.cleanup()


def test_agent_discovery_handler_callable() -> None:
    """Verify AgentDiscoveryHandler is callable with the expected signature."""
    tunnel_manager = SSHTunnelManager()
    handler = AgentDiscoveryHandler(tunnel_manager=tunnel_manager, server_port=9000)
    assert callable(handler)
    assert handler.server_port == 9000
    tunnel_manager.cleanup()


def test_build_cloudflare_client_returns_none_when_not_configured() -> None:
    """Without env vars, _build_cloudflare_client returns None."""
    for key in ("CLOUDFLARE_FORWARDING_URL", "CLOUDFLARE_FORWARDING_USERNAME",
                "CLOUDFLARE_FORWARDING_SECRET", "OWNER_EMAIL"):
        os.environ.pop(key, None)
    result = _build_cloudflare_client()
    assert result is None


def test_build_cloudflare_client_returns_client_when_configured() -> None:
    """With all env vars set, _build_cloudflare_client returns a CloudflareForwardingClient."""
    os.environ["CLOUDFLARE_FORWARDING_URL"] = "https://example.com"
    os.environ["CLOUDFLARE_FORWARDING_USERNAME"] = "user"
    os.environ["CLOUDFLARE_FORWARDING_SECRET"] = "secret"
    os.environ["OWNER_EMAIL"] = "owner@example.com"
    try:
        result = _build_cloudflare_client()
        assert result is not None
    finally:
        for key in ("CLOUDFLARE_FORWARDING_URL", "CLOUDFLARE_FORWARDING_USERNAME",
                    "CLOUDFLARE_FORWARDING_SECRET", "OWNER_EMAIL"):
            os.environ.pop(key, None)


def test_agent_discovery_handler_default_mngr_host_dir() -> None:
    """Verify the default mngr_host_dir is ~/.mngr."""
    tunnel_manager = SSHTunnelManager()
    handler = AgentDiscoveryHandler(tunnel_manager=tunnel_manager, server_port=9000)
    assert handler.mngr_host_dir == Path.home() / ".mngr"
    tunnel_manager.cleanup()


def test_agent_discovery_handler_handles_local_write_error(tmp_path: Path) -> None:
    """Verify local agent write errors are logged but do not propagate.

    Placing a file at the agents/ path prevents mkdir from creating the
    subdirectory, causing an OSError that should be caught and logged.
    """
    tunnel_manager = SSHTunnelManager()
    blocker = tmp_path / "agents"
    blocker.write_text("block")
    handler = AgentDiscoveryHandler(
        tunnel_manager=tunnel_manager,
        server_port=8420,
        mngr_host_dir=tmp_path,
    )
    agent_id = AgentId()
    handler(agent_id, None)
    tunnel_manager.cleanup()
