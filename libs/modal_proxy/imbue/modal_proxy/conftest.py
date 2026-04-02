import pytest

from imbue.modal_proxy.direct import DirectModalInterface


@pytest.fixture
def modal_cli_missing(monkeypatch: pytest.MonkeyPatch) -> DirectModalInterface:
    """Return a DirectModalInterface with PATH set so the modal CLI cannot be found."""
    monkeypatch.setenv("PATH", "/nonexistent_path_for_test")
    return DirectModalInterface()
