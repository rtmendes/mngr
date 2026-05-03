"""Token-refresh glue between session_store and the connector client.

Every authenticated CLI command and every provider operation that talks to
the connector should fetch the access token through ``get_active_token`` so
that an expired (but refreshable) token is transparently rotated before the
real call is made.
"""

from pydantic import SecretStr

from imbue.mngr_imbue_cloud.client import ImbueCloudConnectorClient
from imbue.mngr_imbue_cloud.data_types import AuthSession
from imbue.mngr_imbue_cloud.errors import ImbueCloudAuthError
from imbue.mngr_imbue_cloud.primitives import ImbueCloudAccount
from imbue.mngr_imbue_cloud.session_store import ImbueCloudSessionStore
from imbue.mngr_imbue_cloud.session_store import _decode_jwt_exp


def force_refresh(
    store: ImbueCloudSessionStore,
    client: ImbueCloudConnectorClient,
    account: ImbueCloudAccount,
) -> AuthSession:
    """Unconditionally rotate this account's access + refresh tokens.

    Calls the connector's refresh endpoint regardless of whether the
    cached access token is near expiry, persists the new tokens to disk,
    and returns the rotated AuthSession. Raises ImbueCloudAuthError if the
    session is missing, has no refresh token, or the connector refuses to
    rotate.
    """
    session = store.load_by_account(account)
    if session is None:
        raise ImbueCloudAuthError(
            f"No imbue_cloud session for account {account!s}. "
            f"Run `mngr imbue_cloud auth signin --account {account}` first."
        )
    if session.refresh_token is None:
        raise ImbueCloudAuthError(
            f"No refresh token stored for {account!s}. Run `mngr imbue_cloud auth signin --account {account}` again."
        )
    refreshed = client.auth_refresh_session(session.refresh_token)
    if refreshed.get("status") not in (None, "OK"):
        raise ImbueCloudAuthError(
            f"Refresh rejected by connector: {refreshed.get('message') or refreshed.get('status')}"
        )
    # The connector wraps the tokens in a ``SessionTokens`` body
    # (``{status, tokens: {access_token, refresh_token}}``). Older test
    # fixtures may flatten them, so we accept either shape.
    nested_tokens = refreshed.get("tokens")
    tokens: dict[str, object] = nested_tokens if isinstance(nested_tokens, dict) else refreshed
    new_access = tokens.get("access_token")
    new_refresh_raw = tokens.get("refresh_token")
    new_refresh = new_refresh_raw if isinstance(new_refresh_raw, str) else session.refresh_token.get_secret_value()
    if not isinstance(new_access, str) or not new_access:
        raise ImbueCloudAuthError("Refresh response missing access_token")
    refreshed_session = AuthSession(
        user_id=session.user_id,
        email=session.email,
        display_name=session.display_name,
        access_token=SecretStr(new_access),
        refresh_token=SecretStr(new_refresh),
        access_token_expires_at=_decode_jwt_exp(new_access),
    )
    store.save(refreshed_session)
    return refreshed_session


def get_active_token(
    store: ImbueCloudSessionStore,
    client: ImbueCloudConnectorClient,
    account: ImbueCloudAccount,
) -> SecretStr:
    """Return a fresh access token for ``account``, refreshing if needed.

    Raises ``ImbueCloudAuthError`` if no session exists or refresh fails.
    """
    session = store.load_by_account(account)
    if session is None:
        raise ImbueCloudAuthError(
            f"No imbue_cloud session for account {account!s}. "
            f"Run `mngr imbue_cloud auth signin --account {account}` first."
        )
    if not store.is_access_token_near_expiry(session):
        return session.access_token
    refreshed_session = force_refresh(store, client, account)
    return refreshed_session.access_token
