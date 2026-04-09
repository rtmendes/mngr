"""Test script for verifying kqueue + tty compatibility.

This script is NOT imported as a module -- it is read as a resource file
by test_urwid_tty.py and executed in a tmux session to verify that the
resolved tty path works with macOS kqueue in both piped-stdin and
direct-stdin contexts.

The sentinel ``URWID_TTY_TEST_DONE`` is printed at the end so the test
harness knows when execution has finished.
"""

import selectors
import socket
import sys

from imbue.mngr.cli.urwid_utils import _resolve_real_tty_path

path = _resolve_real_tty_path()
sys.stdout.write(f"resolved_tty_path={path}\n")
sys.stdout.flush()

tty_file = open(path)

rd, wr = socket.socketpair()
rd.setblocking(False)

sel = selectors.DefaultSelector()
try:
    sel.register(rd, selectors.EVENT_READ)
    sel.register(tty_file, selectors.EVENT_READ)
    sys.stdout.write("kqueue_register=OK\n")
except OSError as e:
    sys.stdout.write(f"kqueue_register=FAILED: {e}\n")
finally:
    sel.close()
    rd.close()
    wr.close()
    tty_file.close()

sys.stdout.write("URWID_TTY_TEST_DONE\n")
sys.stdout.flush()
