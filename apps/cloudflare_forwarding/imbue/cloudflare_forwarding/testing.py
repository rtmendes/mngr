"""Test utilities for cloudflare_forwarding."""

from typing import Any

from pydantic import ConfigDict
from pydantic import Field

from imbue.cloudflare_forwarding.forwarding_service import ForwardingService
from imbue.cloudflare_forwarding.primitives import CloudflareDnsRecordId
from imbue.cloudflare_forwarding.primitives import CloudflareTunnelId
from imbue.cloudflare_forwarding.primitives import DomainName
from imbue.imbue_common.mutable_model import MutableModel


class FakeCloudflareClient(MutableModel):
    """In-memory fake of CloudflareClient for testing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tunnels: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tunnel_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dns_records: list[dict[str, Any]] = Field(default_factory=list)
    next_tunnel_id: int = Field(default=1)
    next_record_id: int = Field(default=1)

    def create_tunnel(self, name: str) -> dict[str, Any]:
        tunnel_id = f"tunnel-{self.next_tunnel_id}"
        self.next_tunnel_id += 1
        tunnel = {"id": tunnel_id, "name": name}
        self.tunnels[tunnel_id] = tunnel
        return tunnel

    def list_tunnels(self, name_prefix: str = "") -> list[dict[str, Any]]:
        return [t for t in self.tunnels.values() if t["name"].startswith(name_prefix) or not name_prefix]

    def get_tunnel_by_name(self, name: str) -> dict[str, Any] | None:
        for tunnel in self.tunnels.values():
            if tunnel["name"] == name:
                return tunnel
        return None

    def get_tunnel_token(self, tunnel_id: CloudflareTunnelId) -> str:
        return f"token-for-{tunnel_id}"

    def delete_tunnel(self, tunnel_id: CloudflareTunnelId) -> None:
        self.tunnels.pop(str(tunnel_id), None)
        self.tunnel_configs.pop(str(tunnel_id), None)

    def get_tunnel_configuration(self, tunnel_id: CloudflareTunnelId) -> dict[str, Any]:
        return self.tunnel_configs.get(str(tunnel_id), {"config": {"ingress": [{"service": "http_status:404"}]}})

    def put_tunnel_configuration(self, tunnel_id: CloudflareTunnelId, config: dict[str, Any]) -> None:
        self.tunnel_configs[str(tunnel_id)] = config

    def create_cname_record(self, name: str, target: str) -> dict[str, Any]:
        record_id = f"record-{self.next_record_id}"
        self.next_record_id += 1
        record = {"id": record_id, "name": name, "content": target, "type": "CNAME"}
        self.dns_records.append(record)
        return record

    def list_dns_records(self, name: str = "") -> list[dict[str, Any]]:
        if name:
            return [r for r in self.dns_records if r["name"] == name]
        return list(self.dns_records)

    def delete_dns_record(self, record_id: CloudflareDnsRecordId) -> None:
        self.dns_records = [r for r in self.dns_records if r["id"] != str(record_id)]


def make_forwarding_service(
    fake_client: FakeCloudflareClient | None = None,
) -> tuple[ForwardingService, FakeCloudflareClient]:
    """Create a ForwardingService backed by a FakeCloudflareClient."""
    client = fake_client or FakeCloudflareClient()
    service = ForwardingService(client=client, domain=DomainName("example.com"))
    return service, client
