"""Persistent storage for SuperTokens sessions, keyed by user_id.

Sessions are shared across all `imbue_cloud_*` provider instances, so the
on-disk layout is `<default_host_dir>/providers/imbue_cloud/sessions/<user_id>.json`.
A separate index file `accounts.json` maps email -> user_id so the provider
config (which only has `account = "<email>"`) can resolve a session without
calling the connector.
"""

import base64
import binascii
import json
from datetime import datetime
from datetime import timezone
from pathlib import Path
from threading import Lock

from loguru import logger
from pydantic import Field
from pydantic import SecretStr

from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.mutable_model import MutableModel
from imbue.mngr.utils.file_utils import atomic_write
from imbue.mngr_imbue_cloud.data_types import AuthSession
from imbue.mngr_imbue_cloud.errors import ImbueCloudAuthError
from imbue.mngr_imbue_cloud.primitives import ImbueCloudAccount
from imbue.mngr_imbue_cloud.primitives import SuperTokensUserId

_ACCOUNTS_FILENAME = "accounts.json"


class _AccountIndexEntry(FrozenModel):
    """One row of the email -> user_id index."""

    email: ImbueCloudAccount
    user_id: SuperTokensUserId


def _decode_jwt_exp(access_token: str) -> datetime | None:
    """Best-effort: decode a JWT and return its `exp` claim as a UTC datetime.

    Returns None when the token isn't a recognizable JWT or has no exp.
    Used to know when to refresh transparently before expiry.
    """
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    # JWT uses base64url without padding
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError):
        return None
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        logger.debug("Skipping JWT exp decode: payload is not JSON ({})", exc)
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(float(exp), tz=timezone.utc)


class ImbueCloudSessionStore(MutableModel):
    """Persists SuperTokens sessions keyed by user_id.

    All instances of the imbue_cloud backend share the same sessions dir, so
    multiple provider instances pointing at the same account share their tokens.
    """

    sessions_dir: Path = Field(
        frozen=True,
        description=(
            "Directory containing one <user_id>.json per session and an accounts.json "
            "email -> user_id index. Created on first save."
        ),
    )

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        self._lock = Lock()

    def _ensure_dir(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, user_id: SuperTokensUserId) -> Path:
        return self.sessions_dir / f"{user_id}.json"

    def _index_path(self) -> Path:
        return self.sessions_dir / _ACCOUNTS_FILENAME

    def _load_index(self) -> dict[ImbueCloudAccount, SuperTokensUserId]:
        index_path = self._index_path()
        if not index_path.exists():
            return {}
        try:
            raw = json.loads(index_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read accounts index {}: {}", index_path, exc)
            return {}
        result: dict[ImbueCloudAccount, SuperTokensUserId] = {}
        for entry in raw.get("entries", []):
            try:
                parsed = _AccountIndexEntry.model_validate(entry)
            except (ValueError, TypeError):
                logger.warning("Skipped malformed accounts index entry: {}", entry)
                continue
            result[parsed.email] = parsed.user_id
        return result

    def _save_index(self, index: dict[ImbueCloudAccount, SuperTokensUserId]) -> None:
        self._ensure_dir()
        entries = [
            _AccountIndexEntry(email=email, user_id=user_id).model_dump() for email, user_id in sorted(index.items())
        ]
        atomic_write(self._index_path(), json.dumps({"entries": entries}, indent=2))

    def list_accounts(self) -> tuple[ImbueCloudAccount, ...]:
        """Return all known accounts (whether or not their session is still valid)."""
        with self._lock:
            return tuple(sorted(self._load_index().keys()))

    def load_by_account(self, account: ImbueCloudAccount) -> AuthSession | None:
        """Look up a session by email."""
        with self._lock:
            index = self._load_index()
            user_id = index.get(account)
            if user_id is None:
                return None
            return self._load_by_user_id_unlocked(user_id)

    def load_by_user_id(self, user_id: SuperTokensUserId) -> AuthSession | None:
        with self._lock:
            return self._load_by_user_id_unlocked(user_id)

    def _load_by_user_id_unlocked(self, user_id: SuperTokensUserId) -> AuthSession | None:
        path = self._session_path(user_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text()
        except OSError as exc:
            logger.warning("Failed to read session file {}: {}", path, exc)
            return None
        try:
            return AuthSession.model_validate_json(raw)
        except ValueError as exc:
            logger.warning("Failed to parse session file {}: {}", path, exc)
            return None

    def save(self, session: AuthSession) -> None:
        """Persist a session and update the email -> user_id index.

        SecretStr fields are written as plaintext (Pydantic's default
        ``model_dump_json`` serialises them as ``**********``); the file's
        permissions are 0600 so this is no worse than other secret files.
        """
        with self._lock:
            self._ensure_dir()
            session_path = self._session_path(session.user_id)
            payload = {
                "user_id": str(session.user_id),
                "email": str(session.email),
                "display_name": session.display_name,
                "access_token": session.access_token.get_secret_value(),
                "refresh_token": (
                    session.refresh_token.get_secret_value() if session.refresh_token is not None else None
                ),
                "access_token_expires_at": (
                    session.access_token_expires_at.isoformat()
                    if session.access_token_expires_at is not None
                    else None
                ),
            }
            atomic_write(session_path, json.dumps(payload, indent=2))
            try:
                session_path.chmod(0o600)
            except OSError:
                # Best-effort; on systems where chmod isn't supported we still wrote the file.
                pass
            index = self._load_index()
            index[session.email] = session.user_id
            self._save_index(index)

    def delete_by_account(self, account: ImbueCloudAccount) -> None:
        """Remove the session and email index entry for an account.

        Idempotent: silently no-ops if no session is registered.
        """
        with self._lock:
            index = self._load_index()
            user_id = index.pop(account, None)
            if user_id is not None:
                path = self._session_path(user_id)
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    logger.warning("Failed to remove session file {}: {}", path, exc)
                self._save_index(index)

    def is_access_token_near_expiry(
        self,
        session: AuthSession,
        buffer_seconds: float = 60.0,
    ) -> bool:
        """Return True if the access token expires within ``buffer_seconds``.

        Returns True when the expiry is unknown so callers refresh defensively
        rather than risk sending a stale token.
        """
        if session.access_token_expires_at is None:
            return True
        now = datetime.now(timezone.utc)
        return (session.access_token_expires_at - now).total_seconds() <= buffer_seconds


def make_session_from_tokens(
    user_id: SuperTokensUserId,
    email: ImbueCloudAccount,
    display_name: str | None,
    access_token: str,
    refresh_token: str | None,
) -> AuthSession:
    """Build an AuthSession from raw signin/oauth response tokens."""
    return AuthSession(
        user_id=user_id,
        email=email,
        display_name=display_name,
        access_token=SecretStr(access_token),
        refresh_token=SecretStr(refresh_token) if refresh_token else None,
        access_token_expires_at=_decode_jwt_exp(access_token),
    )


def require_session(store: ImbueCloudSessionStore, account: ImbueCloudAccount) -> AuthSession:
    """Load a session and raise ImbueCloudAuthError if missing.

    Callers that also need an unexpired access token should follow up with a
    transparent refresh through ``ImbueCloudConnectorClient.refresh_if_needed``.
    """
    session = store.load_by_account(account)
    if session is None:
        raise ImbueCloudAuthError(
            f"No imbue_cloud session for account {account!s}. "
            f"Run `mngr imbue_cloud auth signin --account {account}` first."
        )
    return session
