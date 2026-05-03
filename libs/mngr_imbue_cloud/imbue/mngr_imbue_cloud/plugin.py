"""Plugin entry point: registers the provider backend and CLI commands."""

from collections.abc import Sequence

import click

from imbue.mngr.config.data_types import ProviderInstanceConfig
from imbue.mngr.interfaces.provider_backend import ProviderBackendInterface
from imbue.mngr_imbue_cloud import hookimpl
from imbue.mngr_imbue_cloud.backend import ImbueCloudProviderBackend
from imbue.mngr_imbue_cloud.cli.root import imbue_cloud as imbue_cloud_group
from imbue.mngr_imbue_cloud.config import ImbueCloudProviderConfig


@hookimpl
def register_provider_backend() -> tuple[type[ProviderBackendInterface], type[ProviderInstanceConfig]]:
    """Register the imbue_cloud provider backend."""
    return (ImbueCloudProviderBackend, ImbueCloudProviderConfig)


@hookimpl
def register_cli_commands() -> Sequence[click.Command]:
    """Register the top-level `mngr imbue_cloud` command group."""
    return [imbue_cloud_group]
