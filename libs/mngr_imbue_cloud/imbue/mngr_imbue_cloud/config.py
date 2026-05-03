import os
from pathlib import Path

from pydantic import AnyUrl
from pydantic import Field

from imbue.mngr.config.data_types import ProviderInstanceConfig
from imbue.mngr.primitives import ProviderBackendName
from imbue.mngr_imbue_cloud.primitives import IMBUE_CLOUD_BACKEND_NAME
from imbue.mngr_imbue_cloud.primitives import ImbueCloudAccount
from imbue.mngr_imbue_cloud.primitives import get_default_connector_url

CONNECTOR_URL_ENV_VAR = "MNGR__PROVIDERS__IMBUE_CLOUD__CONNECTOR_URL"


class ImbueCloudProviderConfig(ProviderInstanceConfig):
    """Configuration for an imbue_cloud provider instance.

    Two recognized usages:

    - Default instance ``[providers.imbue_cloud]``: ``account`` is unset.
      Callers pass ``-b account=<email>`` to ``mngr create``, or rely on
      single-account fallback when exactly one ``imbue_cloud`` session is
      signed in. Also the form mngr falls back to when no
      ``[providers.imbue_cloud_*]`` block is configured.
    - Per-account instance ``[providers.imbue_cloud_<slug>]``: ``account``
      is bound at config time. Minds writes one of these per signed-in
      account into its mngr settings.toml (see
      ``minds.bootstrap.set_imbue_cloud_provider_for_account`` /
      ``unset_imbue_cloud_provider_for_account``) so per-account
      ``discover_hosts`` works without ambiguity.
    """

    backend: ProviderBackendName = Field(
        default=ProviderBackendName(IMBUE_CLOUD_BACKEND_NAME),
        description="Always 'imbue_cloud' for this backend",
    )
    account: ImbueCloudAccount | None = Field(
        default=None,
        description=(
            "Email of the Imbue Cloud account this provider instance is bound to. "
            "Optional; when unset, callers must pass ``-b account=<email>`` on ``mngr "
            "create`` (or rely on single-account fallback)."
        ),
    )
    connector_url: AnyUrl | None = Field(
        default=None,
        description=(
            "Override for the remote_service_connector base URL. When None, the plugin uses "
            "the value of MNGR__PROVIDERS__IMBUE_CLOUD__CONNECTOR_URL if set, otherwise the "
            "baked-in production default."
        ),
    )
    container_ssh_port: int = Field(
        default=2222,
        description="Port that maps to sshd inside the leased docker container",
    )
    host_dir: Path = Field(
        default=Path("/mngr"),
        description="Base directory for mngr data inside the leased container (matches the pool-host convention)",
    )

    def get_connector_url(self) -> str:
        """Resolve the effective connector URL.

        Precedence: per-instance ``connector_url`` field >
        ``MNGR__PROVIDERS__IMBUE_CLOUD__CONNECTOR_URL`` env >
        baked-in default.
        """
        if self.connector_url is not None:
            return str(self.connector_url).rstrip("/")
        env_value = os.environ.get(CONNECTOR_URL_ENV_VAR)
        if env_value:
            return env_value.rstrip("/")
        return get_default_connector_url().rstrip("/")


def get_provider_data_dir(default_host_dir: Path, instance_name: str) -> Path:
    """Resolve the on-disk state dir for a given provider instance.

    Layout follows the standard convention used by the local provider:
    ``<default_host_dir>/providers/imbue_cloud/<instance_name>/``.
    """
    return default_host_dir.expanduser() / "providers" / IMBUE_CLOUD_BACKEND_NAME / instance_name


def get_shared_sessions_dir(default_host_dir: Path) -> Path:
    """Sessions are shared across all imbue_cloud instances (keyed by user_id)."""
    return default_host_dir.expanduser() / "providers" / IMBUE_CLOUD_BACKEND_NAME / "sessions"
