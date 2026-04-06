import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from imbue.cloudflare_forwarding.auth import verify_credentials
from imbue.cloudflare_forwarding.primitives import Username


def test_verify_credentials_valid(user_credentials_env: None) -> None:
    result = verify_credentials(HTTPBasicCredentials(username="alice", password="secret123"))
    assert result == Username("alice")


def test_verify_credentials_invalid_password(user_credentials_env: None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_credentials(HTTPBasicCredentials(username="alice", password="wrong"))
    assert exc_info.value.status_code == 401


def test_verify_credentials_unknown_user(user_credentials_env: None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_credentials(HTTPBasicCredentials(username="bob", password="secret123"))
    assert exc_info.value.status_code == 401


def test_verify_credentials_missing_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USER_CREDENTIALS", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        verify_credentials(HTTPBasicCredentials(username="alice", password="secret123"))
    assert exc_info.value.status_code == 500
