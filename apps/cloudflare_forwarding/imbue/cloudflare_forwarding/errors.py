class CloudflareForwardingError(Exception):
    """Base exception for all cloudflare_forwarding errors."""

    ...


class CloudflareApiError(CloudflareForwardingError, RuntimeError):
    """Raised when the Cloudflare API returns an error response."""

    def __init__(self, status_code: int, errors: list[dict[str, object]]) -> None:
        self.status_code = status_code
        self.cf_errors = errors
        messages = "; ".join(str(e.get("message", e)) for e in errors)
        super().__init__(f"Cloudflare API error ({status_code}): {messages}")


class TunnelNotFoundError(CloudflareForwardingError, KeyError):
    """Raised when a tunnel name cannot be found."""

    def __init__(self, tunnel_name: str) -> None:
        self.tunnel_name = tunnel_name
        super().__init__(f"Tunnel not found: {tunnel_name}")


class TunnelOwnershipError(CloudflareForwardingError, PermissionError):
    """Raised when a user tries to access a tunnel they don't own."""

    def __init__(self, tunnel_name: str, username: str) -> None:
        self.tunnel_name = tunnel_name
        self.username = username
        super().__init__(f"User '{username}' does not own tunnel '{tunnel_name}'")


class ServiceNotFoundError(CloudflareForwardingError, KeyError):
    """Raised when a service name is not found on a tunnel."""

    def __init__(self, service_name: str, tunnel_name: str) -> None:
        self.service_name = service_name
        self.tunnel_name = tunnel_name
        super().__init__(f"Service '{service_name}' not found on tunnel '{tunnel_name}'")


class InvalidTunnelComponentError(CloudflareForwardingError, ValueError):
    """Raised when a username or agent ID contains characters that would make the tunnel name ambiguous."""

    def __init__(self, component_name: str, value: str, forbidden: str) -> None:
        self.component_name = component_name
        self.value = value
        self.forbidden = forbidden
        super().__init__(
            f"{component_name} '{value}' must not contain '{forbidden}' "
            f"(used as the tunnel name separator)"
        )
