"""HTTP Basic Auth dependency for FastAPI."""

import json
import os
import secrets
from typing import Annotated

from fastapi import Depends
from fastapi import HTTPException
from fastapi.security import HTTPBasic
from fastapi.security import HTTPBasicCredentials

from imbue.cloudflare_forwarding.primitives import Username

_security = HTTPBasic()


def _load_credentials() -> dict[str, str]:
    """Load the user credentials from the USER_CREDENTIALS env var."""
    raw = os.environ.get("USER_CREDENTIALS", "")
    if not raw:
        raise HTTPException(status_code=500, detail="USER_CREDENTIALS not configured")
    result: dict[str, str] = json.loads(raw)
    return result


def verify_credentials(
    credentials: Annotated[HTTPBasicCredentials, Depends(_security)],
) -> Username:
    """FastAPI dependency that validates HTTP Basic Auth and returns the username."""
    creds = _load_credentials()
    expected_secret = creds.get(credentials.username)
    if expected_secret is None or not secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_secret.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return Username(credentials.username)
