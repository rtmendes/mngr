"""Proxy helpers for communicating with the minds desktop client REST API.

The minds desktop client exposes its API to agents via a reverse SSH tunnel.
The URL is written to ``$MNGR_AGENT_STATE_DIR/minds_api_url``. Authentication
uses the ``MINDS_API_KEY`` environment variable as a Bearer token.

For checking forwarding status (GET), we query the Cloudflare forwarding API
directly since the desktop client does not expose a dedicated GET endpoint.
For enabling/disabling (PUT/DELETE), we proxy through the desktop client API.
"""

import os
from pathlib import Path
from typing import Final

import httpx
from loguru import logger as _loguru_logger
from pydantic import Field

from imbue.imbue_common.frozen_model import FrozenModel

logger = _loguru_logger

_MINDS_API_URL_FILENAME: Final[str] = "minds_api_url"
_REQUEST_TIMEOUT_SECONDS: Final[float] = 15.0


class SharingProxyError(RuntimeError):
    """Raised when the sharing proxy cannot communicate with the desktop client."""

    ...


class SharingStatus(FrozenModel):
    """Forwarding status for a server."""

    enabled: bool = Field(description="Whether Cloudflare forwarding is active for this server")
    url: str | None = Field(default=None, description="The global URL if forwarding is enabled")


def _read_minds_api_url() -> str:
    """Read the minds desktop client API URL from the agent state directory.

    Raises SharingProxyError if the file is missing or unreadable.
    """
    agent_state_dir = os.environ.get("MNGR_AGENT_STATE_DIR", "")
    if not agent_state_dir:
        raise SharingProxyError("MNGR_AGENT_STATE_DIR environment variable is not set")

    url_file = Path(agent_state_dir) / _MINDS_API_URL_FILENAME
    if not url_file.exists():
        raise SharingProxyError(f"Minds API URL file not found: {url_file}")

    url = url_file.read_text().strip()
    if not url:
        raise SharingProxyError(f"Minds API URL file is empty: {url_file}")

    return url


def _get_desktop_client_auth_headers() -> dict[str, str]:
    """Build authorization headers for the desktop client using MINDS_API_KEY."""
    api_key = os.environ.get("MINDS_API_KEY", "")
    if not api_key:
        raise SharingProxyError("MINDS_API_KEY environment variable is not set")
    return {"Authorization": f"Bearer {api_key}"}


def _get_own_agent_id() -> str:
    """Return this server's own agent ID from the environment."""
    agent_id = os.environ.get("MNGR_AGENT_ID", "")
    if not agent_id:
        raise SharingProxyError("MNGR_AGENT_ID environment variable is not set")
    return agent_id


def _read_tunnel_token() -> str | None:
    """Read the Cloudflare tunnel token from runtime/secrets.

    Returns None if the file doesn't exist or the token is not found.
    """
    work_dir = os.environ.get("MNGR_AGENT_WORK_DIR", "")
    if not work_dir:
        return None

    secrets_file = Path(work_dir) / "runtime" / "secrets"
    if not secrets_file.exists():
        return None

    try:
        for line in secrets_file.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("export CLOUDFLARE_TUNNEL_TOKEN="):
                return stripped.split("=", 1)[1].strip().strip("'\"")
        return None
    except OSError:
        return None


def get_sharing_status(server_name: str) -> SharingStatus:
    """Fetch the current Cloudflare forwarding status for a server.

    Queries the Cloudflare forwarding API directly using the tunnel token,
    since the desktop client does not expose a GET endpoint for this.
    """
    forwarding_url = os.environ.get("CLOUDFLARE_FORWARDING_URL", "")
    if not forwarding_url:
        raise SharingProxyError("CLOUDFLARE_FORWARDING_URL environment variable is not set")

    tunnel_token = _read_tunnel_token()
    if not tunnel_token:
        raise SharingProxyError("Cloudflare tunnel token not found in runtime/secrets")

    try:
        url = f"{forwarding_url}/tunnels/_/services"
        headers = {"Authorization": f"Bearer {tunnel_token}"}
        response = httpx.get(url, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS)

        if response.status_code != 200:
            raise SharingProxyError(f"Forwarding API returned status {response.status_code}")

        data = response.json()
        for service in data.get("services", []):
            if service.get("service_name") == server_name:
                hostname = service.get("hostname", "")
                if hostname:
                    return SharingStatus(enabled=True, url=f"https://{hostname}")
                return SharingStatus(enabled=True, url=None)

        return SharingStatus(enabled=False)

    except httpx.HTTPError as e:
        raise SharingProxyError(f"Failed to query forwarding API: {e}") from e


def enable_sharing(server_name: str) -> SharingStatus:
    """Enable Cloudflare forwarding for a server via the desktop client API."""
    base_url = _read_minds_api_url()
    agent_id = _get_own_agent_id()
    headers = _get_desktop_client_auth_headers()

    url = f"{base_url}/api/v1/agents/{agent_id}/servers/{server_name}/cloudflare"
    try:
        response = httpx.put(url, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 200:
            return get_sharing_status(server_name)

        error_msg = _extract_error(response)
        raise SharingProxyError(f"Failed to enable sharing: {error_msg}")

    except httpx.HTTPError as e:
        raise SharingProxyError(f"Failed to communicate with desktop client: {e}") from e


def disable_sharing(server_name: str) -> SharingStatus:
    """Disable Cloudflare forwarding for a server via the desktop client API."""
    base_url = _read_minds_api_url()
    agent_id = _get_own_agent_id()
    headers = _get_desktop_client_auth_headers()

    url = f"{base_url}/api/v1/agents/{agent_id}/servers/{server_name}/cloudflare"
    try:
        response = httpx.delete(url, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 200:
            return SharingStatus(enabled=False)

        error_msg = _extract_error(response)
        raise SharingProxyError(f"Failed to disable sharing: {error_msg}")

    except httpx.HTTPError as e:
        raise SharingProxyError(f"Failed to communicate with desktop client: {e}") from e


def _extract_error(response: httpx.Response) -> str:
    """Extract an error message from a non-200 response."""
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = response.json()
            return str(data.get("error", f"HTTP {response.status_code}"))
        except (ValueError, KeyError):
            pass
    return f"HTTP {response.status_code}"
