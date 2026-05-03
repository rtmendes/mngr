"""Translate MINDS_ROOT_NAME into MNGR_HOST_DIR and MNGR_PREFIX.

This must run before any ``imbue.mngr.*`` module is imported, because mngr reads
``MNGR_HOST_DIR`` and ``MNGR_PREFIX`` during its own module-level initialization
(plugin manager construction, config discovery, etc.).

Kept intentionally minimal -- only stdlib and loguru -- so it stays cheap to
import and cannot accidentally pull in mngr before translation happens.
"""

import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Final

import tomlkit
from loguru import logger

MINDS_ROOT_NAME_ENV_VAR: Final[str] = "MINDS_ROOT_NAME"
DEFAULT_MINDS_ROOT_NAME: Final[str] = "minds"
MINDS_ROOT_NAME_PATTERN: Final[str] = r"[a-z0-9_-]+"


def resolve_minds_root_name() -> str:
    """Read MINDS_ROOT_NAME from the environment or return the default.

    Validates the value against MINDS_ROOT_NAME_PATTERN and exits with status
    1 if invalid. Validation is duplicated here (instead of going through a
    pydantic primitive) so this module never has to import pydantic/mngr.
    """
    value = os.environ.get(MINDS_ROOT_NAME_ENV_VAR, DEFAULT_MINDS_ROOT_NAME)
    if not re.fullmatch(MINDS_ROOT_NAME_PATTERN, value):
        logger.error("{} must match {!r}; got {!r}", MINDS_ROOT_NAME_ENV_VAR, MINDS_ROOT_NAME_PATTERN, value)
        sys.exit(1)
    return value


def minds_data_dir_for(root_name: str) -> Path:
    """Return the minds data directory for a given root name (e.g. ~/.minds)."""
    return Path.home() / ".{}".format(root_name)


def mngr_host_dir_for(root_name: str) -> Path:
    """Return the mngr host directory for a given root name (e.g. ~/.minds/mngr)."""
    return minds_data_dir_for(root_name) / "mngr"


def mngr_prefix_for(root_name: str) -> str:
    """Return the mngr prefix for a given root name (e.g. minds-)."""
    return "{}-".format(root_name)


def _ensure_mngr_settings(root_name: str) -> None:
    """Ensure the mngr settings.toml has an SSH provider configured.

    The SSH provider reads dynamic host entries written by the leased-host
    flow. Without this provider, ``mngr rename``/``mngr start`` cannot
    discover agents on leased hosts.

    Only adds the SSH provider section if it is missing -- does not
    overwrite any existing configuration.
    """
    mngr_host_dir = mngr_host_dir_for(root_name)
    root_config_path = mngr_host_dir / "config.toml"
    if not root_config_path.exists():
        return
    root_config = tomllib.loads(root_config_path.read_text())
    profile_id = root_config.get("profile")
    if not profile_id:
        return
    settings_dir = mngr_host_dir / "profiles" / profile_id
    if not settings_dir.exists():
        return
    settings_path = settings_dir / "settings.toml"

    data_dir = minds_data_dir_for(root_name)
    expected_dynamic_hosts_file = str(data_dir / "ssh" / "dynamic_hosts.toml")

    if settings_path.exists():
        existing = tomllib.loads(settings_path.read_text())
        providers = existing.get("providers", {})
        ssh_config = providers.get("ssh", {})
        if (
            ssh_config.get("backend") == "ssh"
            and ssh_config.get("dynamic_hosts_file") == expected_dynamic_hosts_file
            and ssh_config.get("host_dir") == "/mngr"
        ):
            return
    else:
        existing = {}

    # Build the config content with the SSH provider section
    ssh_config = {
        "providers": {
            "ssh": {
                "backend": "ssh",
                "host_dir": "/mngr",
                "dynamic_hosts_file": expected_dynamic_hosts_file,
            },
        },
    }

    if settings_path.exists():
        doc = tomlkit.loads(settings_path.read_text())
        doc.update(ssh_config)
    else:
        doc = tomlkit.document()
        doc.update(ssh_config)

    settings_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = settings_path.with_suffix(".tmp")
    tmp_path.write_text(tomlkit.dumps(doc))
    tmp_path.rename(settings_path)
    logger.debug("Updated mngr settings at {} with SSH provider config", settings_path)


def apply_bootstrap() -> None:
    """Set MNGR_HOST_DIR and MNGR_PREFIX in os.environ from MINDS_ROOT_NAME.

    Must be called before any ``imbue.mngr.*`` module is imported. Explicit
    ``MNGR_HOST_DIR``/``MNGR_PREFIX`` values already in the environment take
    precedence -- they are not overwritten, so tests and advanced users can
    still pin them independently.
    """
    root_name = resolve_minds_root_name()
    os.environ.setdefault("MNGR_HOST_DIR", str(mngr_host_dir_for(root_name)))
    os.environ.setdefault("MNGR_PREFIX", mngr_prefix_for(root_name))
    _ensure_mngr_settings(root_name)


_IMBUE_CLOUD_BACKEND_NAME: Final[str] = "imbue_cloud"


class BootstrapError(ValueError):
    """Raised when minds bootstrap can't compute a derived value (e.g. a slug from an empty email).

    Defined locally instead of importing ``minds.errors`` because this
    module has to stay free of any ``imbue.mngr.*`` / ``click`` imports
    (see the module docstring).
    """


def _slugify_imbue_cloud_account(email: str) -> str:
    """Mirror the plugin's ``slugify_account``.

    Inlined so this module stays mngr-free (it has to be importable before
    ``imbue.mngr`` is on sys.path).
    """
    lowered = email.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not slug:
        raise BootstrapError(f"Cannot slugify imbue_cloud account email: {email!r}")
    return slug


def imbue_cloud_provider_name_for_account(email: str) -> str:
    """Return the provider instance name minds writes for ``email``."""
    return f"imbue_cloud_{_slugify_imbue_cloud_account(email)}"


def _resolve_active_settings_path(root_name: str) -> Path | None:
    """Locate the active mngr settings.toml under the minds host_dir.

    Returns ``None`` if mngr hasn't been initialized in this host_dir yet
    (e.g. minds was just installed and no command has materialized
    ``config.toml`` / a profile dir). Callers should treat ``None`` as
    "skip silently" since there's nothing useful to write yet.
    """
    mngr_host_dir = mngr_host_dir_for(root_name)
    root_config_path = mngr_host_dir / "config.toml"
    if not root_config_path.exists():
        return None
    root_config = tomllib.loads(root_config_path.read_text())
    profile_id = root_config.get("profile")
    if not profile_id:
        return None
    settings_dir = mngr_host_dir / "profiles" / profile_id
    if not settings_dir.exists():
        return None
    return settings_dir / "settings.toml"


def _atomic_write_settings(settings_path: Path, doc: tomlkit.TOMLDocument) -> None:
    """Write ``doc`` to ``settings_path`` via a tmp-file + rename.

    Atomic so a concurrent reader never sees a half-written file.
    """
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = settings_path.with_suffix(".tmp")
    tmp_path.write_text(tomlkit.dumps(doc))
    tmp_path.rename(settings_path)


def set_imbue_cloud_provider_for_account(email: str, *, root_name: str | None = None) -> bool:
    """Register ``[providers.imbue_cloud_<slug>]`` in mngr's settings.toml.

    Called by minds when a SuperTokens session for ``email`` is created
    (signin/signup/oauth-success). Idempotent: a no-op if an equivalent
    entry already exists. Returns ``True`` when the file was modified, so
    callers know whether to bounce ``mngr observe`` (the running process
    needs a restart to see the new provider instance).
    """
    if root_name is None:
        root_name = resolve_minds_root_name()
    settings_path = _resolve_active_settings_path(root_name)
    if settings_path is None:
        return False
    provider_name = imbue_cloud_provider_name_for_account(email)
    if settings_path.exists():
        doc = tomlkit.loads(settings_path.read_text())
    else:
        doc = tomlkit.document()
    providers = doc.setdefault("providers", tomlkit.table())
    existing = providers.get(provider_name)
    if (
        isinstance(existing, dict)
        and existing.get("backend") == _IMBUE_CLOUD_BACKEND_NAME
        and existing.get("account") == email
    ):
        return False
    new_block = tomlkit.table()
    new_block["backend"] = _IMBUE_CLOUD_BACKEND_NAME
    new_block["account"] = email
    providers[provider_name] = new_block
    _atomic_write_settings(settings_path, doc)
    logger.info("imbue_cloud provider {} registered in {}", provider_name, settings_path)
    return True


def unset_imbue_cloud_provider_for_account(email: str, *, root_name: str | None = None) -> bool:
    """Remove ``[providers.imbue_cloud_<slug>]`` from mngr's settings.toml.

    Called by minds on signout. Idempotent: a no-op if no such entry
    exists. Returns ``True`` when the file was modified.
    """
    if root_name is None:
        root_name = resolve_minds_root_name()
    settings_path = _resolve_active_settings_path(root_name)
    if settings_path is None or not settings_path.exists():
        return False
    provider_name = imbue_cloud_provider_name_for_account(email)
    doc = tomlkit.loads(settings_path.read_text())
    providers = doc.get("providers")
    if not isinstance(providers, dict) or provider_name not in providers:
        return False
    del providers[provider_name]
    _atomic_write_settings(settings_path, doc)
    logger.info("imbue_cloud provider {} removed from {}", provider_name, settings_path)
    return True
