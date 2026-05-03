from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import AnyUrl
from pydantic import Field
from pydantic import SecretStr

from imbue.imbue_common.frozen_model import FrozenModel
from imbue.mngr_imbue_cloud.primitives import ImbueCloudAccount
from imbue.mngr_imbue_cloud.primitives import LeaseDbId
from imbue.mngr_imbue_cloud.primitives import SuperTokensUserId


class LeaseAttributes(FrozenModel):
    """Attributes describing what kind of pool host a request needs.

    Sent in the body of POST /hosts/lease as a flexible JSONB-matched dict.
    Only fields explicitly set are included in the request, so the connector
    will not constrain on fields the caller does not care about.
    """

    repo_url: str | None = Field(default=None, description="Repository URL the agent will run from")
    repo_branch_or_tag: str | None = Field(default=None, description="Branch or tag the host was provisioned with")
    cpus: int | None = Field(default=None, description="Number of vCPUs")
    memory_gb: int | None = Field(default=None, description="Memory in GB")
    gpu_count: int | None = Field(default=None, description="Number of GPUs (0 for CPU-only)")

    def to_request_dict(self) -> dict[str, Any]:
        """Drop None values so the connector treats them as 'unconstrained'."""
        return {k: v for k, v in self.model_dump().items() if v is not None}

    @classmethod
    def from_build_args(cls, build_args: Sequence[str] | None) -> "LeaseAttributes":
        """Parse mngr's ``--build-arg KEY=VALUE`` entries into a LeaseAttributes.

        Recognized keys: ``repo_url``, ``repo_branch_or_tag``, ``cpus``,
        ``memory_gb``, ``gpu_count``. Unknown keys are rejected with a clear
        ``ValueError`` so a misspelled flag fails fast rather than silently
        widening the lease match.
        """
        if not build_args:
            return cls()
        parsed: dict[str, Any] = {}
        valid_keys = set(cls.model_fields.keys())
        for entry in build_args:
            if "=" not in entry:
                raise ValueError(f"build_args entry must be KEY=VALUE, got: {entry!r}")
            key, _, value = entry.partition("=")
            key = key.strip()
            value = value.strip()
            if not key:
                raise ValueError(f"build_args entry has empty key: {entry!r}")
            if key not in valid_keys:
                raise ValueError(f"Unknown build_arg key {key!r}; allowed keys are {sorted(valid_keys)}")
            if key in {"cpus", "memory_gb", "gpu_count"}:
                try:
                    parsed[key] = int(value)
                except ValueError as exc:
                    raise ValueError(f"build_arg {key}={value!r} must be an integer") from exc
            else:
                parsed[key] = value
        return cls(**parsed)


class LeaseResult(FrozenModel):
    """Server response from POST /hosts/lease."""

    host_db_id: LeaseDbId = Field(description="Database id of the leased host (UUID)")
    vps_ip: str = Field(description="Public IPv4 of the VPS")
    ssh_port: int = Field(description="SSH port for the VPS itself (root)")
    ssh_user: str = Field(description="SSH username on the VPS")
    container_ssh_port: int = Field(description="Port that maps to the docker container's sshd")
    agent_id: str = Field(description="Pre-baked mngr agent id on the host")
    host_id: str = Field(description="Pre-baked mngr host id")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Attributes the row was matched against")


class LeasedHostInfo(FrozenModel):
    """One entry from GET /hosts."""

    host_db_id: LeaseDbId
    vps_ip: str
    ssh_port: int
    ssh_user: str
    container_ssh_port: int
    agent_id: str
    host_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    leased_at: str = Field(description="ISO-8601 timestamp")


class AuthUser(FrozenModel):
    """User information returned by signin/signup/oauth callbacks."""

    user_id: SuperTokensUserId
    email: ImbueCloudAccount
    display_name: str | None = None


class AuthSession(FrozenModel):
    """Persisted session entry, written to disk per user_id."""

    user_id: SuperTokensUserId
    email: ImbueCloudAccount
    display_name: str | None = None
    access_token: SecretStr = Field(description="SuperTokens JWT access token")
    refresh_token: SecretStr | None = Field(default=None, description="SuperTokens refresh token")
    access_token_expires_at: datetime | None = Field(
        default=None,
        description="UTC datetime at which the access token expires (decoded from JWT exp)",
    )


class LiteLLMKeyMaterial(FrozenModel):
    """Key + base URL returned by POST /keys/create."""

    key: SecretStr
    base_url: AnyUrl


class LiteLLMKeyInfo(FrozenModel):
    """Metadata about a LiteLLM virtual key."""

    token: str
    key_alias: str | None = None
    key_name: str | None = None
    spend: Decimal = Decimal("0")
    max_budget: Decimal | None = None
    budget_duration: str | None = None
    user_id: str | None = None


class TunnelInfo(FrozenModel):
    """A Cloudflare tunnel record."""

    tunnel_name: str
    tunnel_id: str
    token: SecretStr | None = None
    services: tuple[str, ...] = ()


class ServiceInfo(FrozenModel):
    """A service forwarded over a Cloudflare tunnel."""

    service_name: str
    service_url: str
    hostname: str


class AuthPolicy(FrozenModel):
    """Cloudflare Access policy expressed as allowed emails / IDPs."""

    emails: tuple[str, ...] = ()
    email_domains: tuple[str, ...] = ()
    require_idp: tuple[str, ...] = ()
