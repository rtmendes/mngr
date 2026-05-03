"""Plugin entry point: registers the provider backend and CLI commands."""

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click
from loguru import logger

from imbue.mngr.config.data_types import ProviderInstanceConfig
from imbue.mngr.interfaces.provider_backend import ProviderBackendInterface
from imbue.mngr_imbue_cloud import hookimpl
from imbue.mngr_imbue_cloud.backend import ImbueCloudProviderBackend
from imbue.mngr_imbue_cloud.cli.root import imbue_cloud as imbue_cloud_group
from imbue.mngr_imbue_cloud.config import ImbueCloudProviderConfig
from imbue.mngr_imbue_cloud.config import get_shared_sessions_dir
from imbue.mngr_imbue_cloud.primitives import IMBUE_CLOUD_BACKEND_NAME
from imbue.mngr_imbue_cloud.primitives import slugify_account


@hookimpl
def register_provider_backend() -> tuple[type[ProviderBackendInterface], type[ProviderInstanceConfig]]:
    """Register the imbue_cloud provider backend."""
    return (ImbueCloudProviderBackend, ImbueCloudProviderConfig)


@hookimpl
def register_cli_commands() -> Sequence[click.Command]:
    """Register the top-level `mngr imbue_cloud` command group."""
    return [imbue_cloud_group]


@hookimpl
def on_load_config(config_dict: dict[str, Any]) -> None:
    """Auto-register a provider instance for every signed-in imbue_cloud account.

    Sessions live at ``<default_host_dir>/providers/imbue_cloud/sessions/<user_id>.json``;
    each one's ``email`` field becomes a provider instance keyed by
    ``imbue_cloud_<account-slug>``. Once an account is signed in, ``mngr
    create --provider imbue_cloud_<slug> --new-host`` works without a manual
    ``[providers.imbue_cloud_<slug>]`` block in ``~/.mngr/config.toml``.

    Existing config entries are NOT overwritten -- if the user has explicitly
    configured a provider with the same name, their settings win.
    """
    default_host_dir = Path(os.environ.get("MNGR_HOST_DIR") or "~/.mngr").expanduser()
    sessions_dir = get_shared_sessions_dir(default_host_dir)
    if not sessions_dir.is_dir():
        return
    providers = config_dict.setdefault("providers", {})
    for session_path in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(session_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("imbue_cloud: skipping unreadable session {}: {}", session_path, exc)
            continue
        email = data.get("email")
        if not email:
            continue
        provider_name = f"imbue_cloud_{slugify_account(email)}"
        if provider_name in providers:
            continue
        providers[provider_name] = {
            "backend": IMBUE_CLOUD_BACKEND_NAME,
            "account": email,
        }
