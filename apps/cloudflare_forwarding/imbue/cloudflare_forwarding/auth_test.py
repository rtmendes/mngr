import json
import os

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from imbue.cloudflare_forwarding.auth import verify_credentials
from imbue.cloudflare_forwarding.primitives import Username


def test_verify_credentials_valid() -> None:
    os.environ["USER_CREDENTIALS"] = json.dumps({"alice": "secret123"})
    try:
        result = verify_credentials(HTTPBasicCredentials(username="alice", password="secret123"))
        assert result == Username("alice")
    finally:
        del os.environ["USER_CREDENTIALS"]


def test_verify_credentials_invalid_password() -> None:
    os.environ["USER_CREDENTIALS"] = json.dumps({"alice": "secret123"})
    try:
        with pytest.raises(HTTPException) as exc_info:
            verify_credentials(HTTPBasicCredentials(username="alice", password="wrong"))
        assert exc_info.value.status_code == 401
    finally:
        del os.environ["USER_CREDENTIALS"]


def test_verify_credentials_unknown_user() -> None:
    os.environ["USER_CREDENTIALS"] = json.dumps({"alice": "secret123"})
    try:
        with pytest.raises(HTTPException) as exc_info:
            verify_credentials(HTTPBasicCredentials(username="bob", password="secret123"))
        assert exc_info.value.status_code == 401
    finally:
        del os.environ["USER_CREDENTIALS"]


def test_verify_credentials_missing_env_var() -> None:
    os.environ.pop("USER_CREDENTIALS", None)
    with pytest.raises(HTTPException) as exc_info:
        verify_credentials(HTTPBasicCredentials(username="alice", password="secret123"))
    assert exc_info.value.status_code == 500
