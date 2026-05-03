"""Shared helpers for imbue_cloud CLI subcommands.

Each subcommand needs to find the on-disk session store and to build a
connector client. We deliberately don't bring up the full mngr command
context here -- these commands are plugin-local and don't need to load
plugins, agent types, or providers.
"""

import functools as _functools
import json as _json
import os
import sys
from pathlib import Path
from typing import Any
from typing import NoReturn

import click
from pydantic import AnyUrl

from imbue.mngr_imbue_cloud.client import ImbueCloudConnectorClient
from imbue.mngr_imbue_cloud.config import CONNECTOR_URL_ENV_VAR
from imbue.mngr_imbue_cloud.config import get_shared_sessions_dir
from imbue.mngr_imbue_cloud.errors import ImbueCloudError
from imbue.mngr_imbue_cloud.primitives import ImbueCloudAccount
from imbue.mngr_imbue_cloud.primitives import get_default_connector_url
from imbue.mngr_imbue_cloud.session_store import ImbueCloudSessionStore

_DEFAULT_HOST_DIR_ENV_VAR = "MNGR_HOST_DIR"


def get_default_host_dir() -> Path:
    """Resolve the active mngr default host dir.

    Honors ``MNGR_HOST_DIR`` (the same env var mngr uses), defaulting to ``~/.mngr``.
    """
    env_value = os.environ.get(_DEFAULT_HOST_DIR_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser()
    return Path("~/.mngr").expanduser()


def make_session_store() -> ImbueCloudSessionStore:
    return ImbueCloudSessionStore(sessions_dir=get_shared_sessions_dir(get_default_host_dir()))


def resolve_connector_url(override: str | None) -> str:
    """Resolve the connector URL: explicit flag > env var > baked default."""
    if override:
        return override.rstrip("/")
    env_value = os.environ.get(CONNECTOR_URL_ENV_VAR)
    if env_value:
        return env_value.rstrip("/")
    return get_default_connector_url().rstrip("/")


def make_connector_client(connector_url: str | None) -> ImbueCloudConnectorClient:
    return ImbueCloudConnectorClient(base_url=AnyUrl(resolve_connector_url(connector_url)))


def emit_json(data: Any) -> None:
    """Print a JSON-serialisable object to stdout, followed by a newline."""
    click.echo(_json.dumps(data, indent=2, default=str))


def fail_with_json(message: str, *, exit_code: int = 1, **extra: Any) -> NoReturn:
    """Print a JSON error body to stderr and exit with the given code."""
    body: dict[str, Any] = {"error": message}
    body.update(extra)
    click.echo(_json.dumps(body, indent=2, default=str), err=True)
    sys.exit(exit_code)


def parse_account(value: str) -> ImbueCloudAccount:
    try:
        return ImbueCloudAccount(value)
    except ValueError as exc:
        fail_with_json(f"Invalid account email: {exc}")


def handle_imbue_cloud_errors(func):
    """Decorator that translates ImbueCloudError into structured JSON failures."""

    @_functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ImbueCloudError as exc:
            fail_with_json(str(exc), error_class=type(exc).__name__)

    return wrapper
