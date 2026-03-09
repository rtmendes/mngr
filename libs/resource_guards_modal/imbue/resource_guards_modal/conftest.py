import pytest

import imbue.resource_guards.resource_guards as resource_guards


@pytest.fixture()
def isolated_guard_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate resource guard module state for guard tests."""
    monkeypatch.setattr(resource_guards, "_guard_wrapper_dir", None)
    monkeypatch.setattr(resource_guards, "_owns_guard_wrapper_dir", False)
    monkeypatch.setattr(resource_guards, "_session_env_patcher", None)
    monkeypatch.setattr(resource_guards, "_guarded_resources", [])
    monkeypatch.setattr(resource_guards, "_registered_sdk_guards", [])
