import io
import os
from pathlib import Path
from unittest.mock import patch

from imbue.mngr.cli.urwid_utils import has_interactive_terminal
from imbue.mngr.cli.urwid_utils import resolve_real_tty_path


def test_has_interactive_terminal_when_stdin_is_tty() -> None:
    """Returns True immediately when stdin reports as a tty."""
    assert has_interactive_terminal(stdin_is_tty=True) is True


def test_has_interactive_terminal_falls_back_to_dev_tty(tmp_path: Path) -> None:
    """Returns True when stdin is not a tty but a controlling terminal exists."""
    # Create a real file to stand in for /dev/tty.  os.open() on a regular
    # file succeeds, which is sufficient for the probe logic.
    fake_tty = tmp_path / "fake_tty"
    fake_tty.touch()
    assert has_interactive_terminal(stdin_is_tty=False, tty_path=fake_tty) is True


def test_has_interactive_terminal_no_terminal(tmp_path: Path) -> None:
    """Returns False when stdin is not a tty and no controlling terminal exists."""
    nonexistent = tmp_path / "nonexistent"
    assert has_interactive_terminal(stdin_is_tty=False, tty_path=nonexistent) is False


class _FakeStream(io.BytesIO):
    """BytesIO with a fileno method for testing."""

    def fileno(self) -> int:
        return 99


def test_resolve_real_tty_path_uses_stdout_ttyname() -> None:
    """Resolves the real pty device path from stdout when available."""
    fake_stdout = _FakeStream()
    with (
        patch.object(os, "isatty", return_value=True),
        patch.object(os, "ttyname", return_value="/dev/ttys042"),
        patch("imbue.mngr.cli.urwid_utils.sys") as mock_sys,
    ):
        mock_sys.stdout = fake_stdout
        mock_sys.stderr = io.BytesIO()
        result = resolve_real_tty_path()
    assert result == "/dev/ttys042"


def test_resolve_real_tty_path_falls_back_to_dev_tty() -> None:
    """Falls back to /dev/tty when stdout and stderr are not ttys."""
    non_tty = io.BytesIO()
    with patch("imbue.mngr.cli.urwid_utils.sys") as mock_sys:
        mock_sys.stdout = non_tty
        mock_sys.stderr = non_tty
        result = resolve_real_tty_path()
    assert result == "/dev/tty"
