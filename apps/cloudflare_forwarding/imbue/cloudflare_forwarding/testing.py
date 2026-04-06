"""Test utilities for cloudflare_forwarding."""

from typing import Any

from imbue.cloudflare_forwarding.app import ServiceInfo
from imbue.cloudflare_forwarding.app import ServiceNotFoundError
from imbue.cloudflare_forwarding.app import TunnelInfo
from imbue.cloudflare_forwarding.app import TunnelNotFoundError
from imbue.cloudflare_forwarding.app import TunnelOwnershipError
from imbue.cloudflare_forwarding.app import TUNNEL_NAME_SEP
from imbue.cloudflare_forwarding.app import non_catchall_rules
from imbue.cloudflare_forwarding.app import wrap_ingress
from imbue.cloudflare_forwarding.app import extract_agent_id
from imbue.cloudflare_forwarding.app import extract_service_name
from imbue.cloudflare_forwarding.app import make_hostname
from imbue.cloudflare_forwarding.app import make_tunnel_name


class FakeCloudflareClient:
    """In-memory fake that mirrors the Cloudflare API functions used by ForwardingCtx."""

    def __init__(self) -> None:
        self.tunnels: dict[str, dict[str, Any]] = {}
        self.tunnel_configs: dict[str, dict[str, Any]] = {}
        self.dns_records: list[dict[str, Any]] = []
        self._next_tunnel_id = 1
        self._next_record_id = 1

    def create_tunnel(self, name: str) -> dict[str, Any]:
        tunnel_id = f"tunnel-{self._next_tunnel_id}"
        self._next_tunnel_id += 1
        tunnel = {"id": tunnel_id, "name": name}
        self.tunnels[tunnel_id] = tunnel
        return tunnel

    def list_tunnels(self, include_prefix: str = "") -> list[dict[str, Any]]:
        results = list(self.tunnels.values())
        if include_prefix:
            results = [t for t in results if t["name"].startswith(include_prefix)]
        return results

    def get_tunnel_by_name(self, name: str) -> dict[str, Any] | None:
        for tunnel in self.tunnels.values():
            if tunnel["name"] == name:
                return tunnel
        return None

    def get_tunnel_token(self, tunnel_id: str) -> str:
        return f"token-for-{tunnel_id}"

    def delete_tunnel(self, tunnel_id: str) -> None:
        self.tunnels.pop(tunnel_id, None)
        self.tunnel_configs.pop(tunnel_id, None)

    def get_tunnel_config(self, tunnel_id: str) -> dict[str, Any]:
        return self.tunnel_configs.get(tunnel_id, {"config": {"ingress": [{"service": "http_status:404"}]}})

    def put_tunnel_config(self, tunnel_id: str, config: dict[str, Any]) -> None:
        self.tunnel_configs[tunnel_id] = config

    def create_cname(self, name: str, target: str) -> dict[str, Any]:
        record_id = f"record-{self._next_record_id}"
        self._next_record_id += 1
        record = {"id": record_id, "name": name, "content": target, "type": "CNAME"}
        self.dns_records.append(record)
        return record

    def list_dns_records(self, name: str = "") -> list[dict[str, Any]]:
        if name:
            return [r for r in self.dns_records if r["name"] == name]
        return list(self.dns_records)

    def delete_dns_record(self, record_id: str) -> None:
        self.dns_records = [r for r in self.dns_records if r["id"] != record_id]


class FakeForwardingCtx:
    """ForwardingCtx-like object backed by FakeCloudflareClient for testing."""

    def __init__(self, domain: str = "example.com") -> None:
        self.fake = FakeCloudflareClient()
        self.account_id = "test-account"
        self.zone_id = "test-zone"
        self.domain = domain

    def verify_ownership(self, tunnel_name: str, username: str) -> None:
        if not tunnel_name.startswith(f"{username}{TUNNEL_NAME_SEP}"):
            raise TunnelOwnershipError(tunnel_name, username)

    def get_tunnel_or_raise(self, tunnel_name: str) -> dict[str, Any]:
        tunnel = self.fake.get_tunnel_by_name(tunnel_name)
        if tunnel is None:
            raise TunnelNotFoundError(tunnel_name)
        return tunnel

    def create_tunnel(self, username: str, agent_id: str) -> TunnelInfo:
        name = make_tunnel_name(username, agent_id)
        existing = self.fake.get_tunnel_by_name(name)
        if existing is not None:
            tid = existing["id"]
            token = self.fake.get_tunnel_token(tid)
            services = self._list_services(tid, name, username)
            return TunnelInfo(tunnel_name=name, tunnel_id=tid, token=token, services=services)

        result = self.fake.create_tunnel(name)
        tid = result["id"]
        token = self.fake.get_tunnel_token(tid)
        self.fake.put_tunnel_config(tid, wrap_ingress([]))
        return TunnelInfo(tunnel_name=name, tunnel_id=tid, token=token, services=[])

    def list_tunnels(self, username: str) -> list[TunnelInfo]:
        prefix = f"{username}{TUNNEL_NAME_SEP}"
        tunnels = self.fake.list_tunnels(include_prefix=prefix)
        result: list[TunnelInfo] = []
        for t in tunnels:
            name = t["name"]
            if not name.startswith(prefix):
                continue
            tid = t["id"]
            services = self._list_services(tid, name, username)
            result.append(TunnelInfo(tunnel_name=name, tunnel_id=tid, services=services))
        return result

    def delete_tunnel(self, tunnel_name: str, username: str) -> None:
        self.verify_ownership(tunnel_name, username)
        tunnel = self.get_tunnel_or_raise(tunnel_name)
        tid = tunnel["id"]
        config = self.fake.get_tunnel_config(tid)
        for rule in non_catchall_rules(config.get("config", {}).get("ingress", [])):
            hostname = rule.get("hostname", "")
            if hostname:
                self._delete_dns_by_name(hostname)
        self.fake.put_tunnel_config(tid, wrap_ingress([]))
        self.fake.delete_tunnel(tid)

    def add_service(self, tunnel_name: str, username: str, service_name: str, service_url: str) -> ServiceInfo:
        self.verify_ownership(tunnel_name, username)
        tunnel = self.get_tunnel_or_raise(tunnel_name)
        tid = tunnel["id"]
        agent_id = extract_agent_id(tunnel_name, username)
        hostname = make_hostname(service_name, agent_id, username, self.domain)
        self.fake.create_cname(hostname, f"{tid}.cfargotunnel.com")
        config = self.fake.get_tunnel_config(tid)
        rules = non_catchall_rules(config.get("config", {}).get("ingress", []))
        rules.append({"hostname": hostname, "service": service_url})
        self.fake.put_tunnel_config(tid, wrap_ingress(rules))
        return ServiceInfo(service_name=service_name, hostname=hostname, service_url=service_url)

    def remove_service(self, tunnel_name: str, username: str, service_name: str) -> None:
        self.verify_ownership(tunnel_name, username)
        tunnel = self.get_tunnel_or_raise(tunnel_name)
        tid = tunnel["id"]
        agent_id = extract_agent_id(tunnel_name, username)
        hostname = make_hostname(service_name, agent_id, username, self.domain)
        config = self.fake.get_tunnel_config(tid)
        rules = non_catchall_rules(config.get("config", {}).get("ingress", []))
        new_rules = [r for r in rules if r.get("hostname") != hostname]
        if len(new_rules) == len(rules):
            raise ServiceNotFoundError(service_name, tunnel_name)
        self.fake.put_tunnel_config(tid, wrap_ingress(new_rules))
        self._delete_dns_by_name(hostname)

    def _list_services(self, tunnel_id: str, tunnel_name: str, username: str) -> list[ServiceInfo]:
        agent_id = extract_agent_id(tunnel_name, username)
        config = self.fake.get_tunnel_config(tunnel_id)
        rules = non_catchall_rules(config.get("config", {}).get("ingress", []))
        services: list[ServiceInfo] = []
        for rule in rules:
            hostname = rule.get("hostname", "")
            svc_url = rule.get("service", "")
            svc_name = extract_service_name(hostname, agent_id, username, self.domain)
            if svc_name is not None:
                services.append(ServiceInfo(service_name=svc_name, hostname=hostname, service_url=svc_url))
        return services

    def _delete_dns_by_name(self, hostname: str) -> None:
        records = self.fake.list_dns_records(name=hostname)
        for record in records:
            self.fake.delete_dns_record(record["id"])
