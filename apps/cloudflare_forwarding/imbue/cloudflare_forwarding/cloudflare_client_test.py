import json

import httpx
import pytest

from imbue.cloudflare_forwarding.cloudflare_client import CloudflareClient
from imbue.cloudflare_forwarding.errors import CloudflareApiError
from imbue.cloudflare_forwarding.primitives import CloudflareAccountId
from imbue.cloudflare_forwarding.primitives import CloudflareDnsRecordId
from imbue.cloudflare_forwarding.primitives import CloudflareTunnelId
from imbue.cloudflare_forwarding.primitives import CloudflareZoneId


def _success_response(result: object) -> httpx.Response:
    """Build a mock Cloudflare success response."""
    return httpx.Response(
        200,
        json={"success": True, "errors": [], "messages": [], "result": result},
    )


def _error_response(status_code: int, errors: list[dict[str, object]]) -> httpx.Response:
    """Build a mock Cloudflare error response."""
    return httpx.Response(
        status_code,
        json={"success": False, "errors": errors, "messages": []},
    )


def _make_client(transport: httpx.MockTransport) -> CloudflareClient:
    """Create a CloudflareClient with a mock transport."""
    http_client = httpx.Client(
        base_url="https://api.cloudflare.com/client/v4",
        headers={"Authorization": "Bearer test-token"},
        transport=transport,
    )
    return CloudflareClient(
        http_client=http_client,
        account_id=CloudflareAccountId("test-account"),
        zone_id=CloudflareZoneId("test-zone"),
    )


def test_create_tunnel_sends_correct_request() -> None:
    tunnel_result = {"id": "tunnel-uuid", "name": "alice-agent1"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/cfd_tunnel" in str(request.url)
        body = json.loads(request.content)
        assert body["name"] == "alice-agent1"
        assert body["config_src"] == "cloudflare"
        return _success_response(tunnel_result)

    client = _make_client(httpx.MockTransport(handler))
    result = client.create_tunnel("alice-agent1")
    assert result["id"] == "tunnel-uuid"


def test_create_tunnel_raises_on_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_response(400, [{"code": 1000, "message": "bad request"}])

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(CloudflareApiError) as exc_info:
        client.create_tunnel("test")
    assert exc_info.value.status_code == 400


def test_list_tunnels_with_prefix() -> None:
    tunnels = [
        {"id": "t1", "name": "alice-agent1"},
        {"id": "t2", "name": "alice-agent2"},
        {"id": "t3", "name": "bob-agent1"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "is_deleted=false" in str(request.url)
        return _success_response(tunnels)

    client = _make_client(httpx.MockTransport(handler))
    result = client.list_tunnels(name_prefix="alice-")
    assert len(result) == 2
    assert all(t["name"].startswith("alice-") for t in result)


def test_get_tunnel_by_name_finds_exact_match() -> None:
    tunnels = [{"id": "t1", "name": "alice-agent1"}, {"id": "t2", "name": "alice-agent123"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "name=alice-agent1" in str(request.url)
        return _success_response(tunnels)

    client = _make_client(httpx.MockTransport(handler))
    result = client.get_tunnel_by_name("alice-agent1")
    assert result is not None
    assert result["id"] == "t1"


def test_get_tunnel_by_name_returns_none_when_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "name=nonexistent" in str(request.url)
        return _success_response([])

    client = _make_client(httpx.MockTransport(handler))
    result = client.get_tunnel_by_name("nonexistent")
    assert result is None


def test_get_tunnel_token_returns_token_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/token" in str(request.url)
        return _success_response("eyJ0dW5uZWxJZCI6InRlc3QifQ==")

    client = _make_client(httpx.MockTransport(handler))
    token = client.get_tunnel_token(CloudflareTunnelId("tunnel-uuid"))
    assert token == "eyJ0dW5uZWxJZCI6InRlc3QifQ=="


def test_delete_tunnel_sends_delete_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return _success_response({})

    client = _make_client(httpx.MockTransport(handler))
    client.delete_tunnel(CloudflareTunnelId("tunnel-uuid"))


def test_get_tunnel_configuration() -> None:
    config = {"config": {"ingress": [{"service": "http_status:404"}]}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/configurations" in str(request.url)
        return _success_response(config)

    client = _make_client(httpx.MockTransport(handler))
    result = client.get_tunnel_configuration(CloudflareTunnelId("tunnel-uuid"))
    assert result["config"]["ingress"][0]["service"] == "http_status:404"


def test_put_tunnel_configuration() -> None:
    new_config = {
        "config": {
            "ingress": [
                {"hostname": "test.example.com", "service": "http://localhost:8080"},
                {"service": "http_status:404"},
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        body = json.loads(request.content)
        assert body == new_config
        return _success_response({})

    client = _make_client(httpx.MockTransport(handler))
    client.put_tunnel_configuration(CloudflareTunnelId("tunnel-uuid"), new_config)


def test_create_cname_record() -> None:
    record = {"id": "record-1", "type": "CNAME", "name": "test.example.com"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["type"] == "CNAME"
        assert body["proxied"] is True
        return _success_response(record)

    client = _make_client(httpx.MockTransport(handler))
    result = client.create_cname_record("test.example.com", "tunnel-uuid.cfargotunnel.com")
    assert result["id"] == "record-1"


def test_list_dns_records() -> None:
    records = [{"id": "r1", "name": "test.example.com"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "type=CNAME" in str(request.url)
        return _success_response(records)

    client = _make_client(httpx.MockTransport(handler))
    result = client.list_dns_records(name="test.example.com")
    assert len(result) == 1


def test_delete_dns_record() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return _success_response({})

    client = _make_client(httpx.MockTransport(handler))
    client.delete_dns_record(CloudflareDnsRecordId("record-1"))
