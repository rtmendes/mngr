import pytest

from imbue.minds.desktop_client.cloudflare_client import RemoteServiceConnectorUrl
from imbue.minds.desktop_client.host_pool_client import HostPoolClient
from imbue.minds.desktop_client.host_pool_client import HostPoolEmptyError
from imbue.minds.desktop_client.host_pool_client import HostPoolError
from imbue.minds.errors import MindError


def _make_client(url: str = "http://127.0.0.1:1") -> HostPoolClient:
    return HostPoolClient(
        connector_url=RemoteServiceConnectorUrl(url),
    )


def test_url_construction_strips_trailing_slash() -> None:
    client = _make_client("http://example.com/")
    assert client._url("/hosts/lease") == "http://example.com/hosts/lease"


def test_url_construction_without_trailing_slash() -> None:
    client = _make_client("http://example.com")
    assert client._url("/hosts/lease") == "http://example.com/hosts/lease"


def test_host_pool_error_inherits_from_mind_error() -> None:
    """HostPoolError should be catchable as a MindError."""
    error = HostPoolError("test")
    assert isinstance(error, MindError)


def test_host_pool_empty_error_inherits_from_host_pool_error() -> None:
    """HostPoolEmptyError should be catchable as a HostPoolError."""
    error = HostPoolEmptyError("no hosts")
    assert isinstance(error, HostPoolError)
    assert isinstance(error, MindError)


def test_lease_host_raises_on_connection_error() -> None:
    """Leasing from an unreachable server raises HostPoolError."""
    client = _make_client()
    with pytest.raises(HostPoolError, match="lease request failed"):
        client.lease_host(access_token="token", ssh_public_key="ssh-ed25519 AAAA", version="v1")


def test_release_host_returns_false_on_connection_error() -> None:
    """Releasing to an unreachable server returns False without raising."""
    client = _make_client()
    result = client.release_host(access_token="token", host_db_id=42)
    assert result is False


def test_list_leased_hosts_returns_empty_on_connection_error() -> None:
    """Listing from an unreachable server returns an empty list without raising."""
    client = _make_client()
    result = client.list_leased_hosts(access_token="token")
    assert result == []
