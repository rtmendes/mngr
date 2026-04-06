import json
from collections.abc import Iterator

import pytest


@pytest.fixture()
def user_credentials_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set the USER_CREDENTIALS env var for auth tests."""
    monkeypatch.setenv("USER_CREDENTIALS", json.dumps({"alice": "secret123"}))
    yield
