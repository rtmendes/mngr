"""Acceptance tests for connect-related functionality."""

import subprocess

import pytest

from imbue.mngr.api.connect import build_post_attach_resize_script
from imbue.mngr.utils.polling import wait_for
from imbue.mngr.utils.testing import cleanup_tmux_session


@pytest.mark.tmux
def test_post_attach_resize_delivers_sigwinch_to_child_process(mngr_test_prefix: str, tmp_path) -> None:
    """Verify build_post_attach_resize_script delivers SIGWINCH to pane processes.

    When connecting to a remote agent via SSH, the tmux session may have been
    created at 200x50 but the user's terminal is a different size. The resize
    script must deliver SIGWINCH to the agent process so it redraws.

    This test creates a session whose initial command is a SIGWINCH catcher,
    then runs the actual resize script from connect.py and verifies SIGWINCH
    was delivered. It is a regression test: the old approach (pkill -f with a
    process name pattern) failed on macOS where Claude's process title shows
    as its version number, and was dependent on a && chain that could silently
    skip the SIGWINCH step.
    """
    session_name = f"{mngr_test_prefix}sigwinch-connect"
    marker_file = tmp_path / "sigwinch_received"

    # Use the SIGWINCH catcher as the session's initial command (not a child
    # of a shell) to avoid macOS-specific pgrep timing issues.
    catcher_cmd = (
        f'python3 -c "'
        f"import signal, pathlib, threading; "
        f"signal.signal(signal.SIGWINCH, lambda s,f: pathlib.Path('{marker_file}').write_text('received')); "
        f"threading.Event().wait()"
        f'"'
    )

    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50", catcher_cmd],
            check=True,
        )

        # Wait for the pane process to be python3 (the catcher)
        wait_for(
            lambda: "python"
            in subprocess.run(
                ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_current_command}"],
                capture_output=True,
                text=True,
            ).stdout.lower(),
            timeout=5.0,
            error_message="SIGWINCH catcher did not start in the tmux pane",
        )

        # Run the actual resize script from connect.py
        resize_script = build_post_attach_resize_script(session_name)
        subprocess.run(["bash", "-c", resize_script], check=True)

        wait_for(
            lambda: marker_file.exists(),
            timeout=3.0,
            error_message=(
                "SIGWINCH did not reach the pane process after running "
                "build_post_attach_resize_script. The resize mechanism should "
                "deliver SIGWINCH to pane processes."
            ),
        )

    finally:
        cleanup_tmux_session(session_name)
