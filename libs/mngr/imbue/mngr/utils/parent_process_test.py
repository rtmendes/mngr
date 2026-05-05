import os
import threading
from uuid import uuid4

from imbue.concurrency_group.concurrency_group import ConcurrencyGroup
from imbue.mngr.utils.parent_process import _PARENT_POLL_INTERVAL_SECONDS
from imbue.mngr.utils.parent_process import _read_grandparent_pid
from imbue.mngr.utils.parent_process import start_grandparent_death_watcher
from imbue.mngr.utils.parent_process import start_parent_death_watcher


def test_start_parent_death_watcher_starts_thread_in_concurrency_group() -> None:
    """Verify the watcher thread is started and is alive."""
    with ConcurrencyGroup(name=f"test-{uuid4().hex}") as cg:
        start_parent_death_watcher(cg)
        threads = [t for t in cg._threads if t.thread.name == "parent-death-watcher"]
        assert len(threads) == 1
        assert threads[0].thread.is_alive()


def test_parent_death_watcher_does_not_fire_when_parent_alive() -> None:
    """Verify the watcher thread stays alive through a poll cycle when the parent is still alive."""
    with ConcurrencyGroup(name=f"test-{uuid4().hex}") as cg:
        start_parent_death_watcher(cg)
        threads = [t for t in cg._threads if t.thread.name == "parent-death-watcher"]
        assert len(threads) == 1
        watcher_thread = threads[0].thread

        # Poll until the watcher has had time for at least one full poll cycle.
        # If the watcher incorrectly fired, the thread would exit after detecting
        # a (false) parent death.
        deadline = threading.Event()
        deadline.wait(timeout=_PARENT_POLL_INTERVAL_SECONDS + 1.0)
        assert watcher_thread.is_alive(), "Watcher thread exited unexpectedly during poll cycle"


def test_read_grandparent_pid_returns_alive_grandparent() -> None:
    """The helper should return a positive PID when run under a normal process tree.

    Pytest under xdist runs each test inside a worker that itself has a real
    parent and grandparent, so this should always resolve to something
    signalable.
    """
    grandparent_pid = _read_grandparent_pid()
    assert grandparent_pid is not None
    assert grandparent_pid > 1
    # Verify the PID exists right now (no signal sent).
    os.kill(grandparent_pid, 0)


def test_start_grandparent_death_watcher_starts_thread_when_resolvable() -> None:
    """When a grandparent exists, the watcher thread is started and stays alive."""
    with ConcurrencyGroup(name=f"test-{uuid4().hex}") as cg:
        start_grandparent_death_watcher(cg)
        threads = [t for t in cg._threads if t.thread.name == "grandparent-death-watcher"]
        # If the test runner has no resolvable grandparent (very unusual), the
        # watcher is a no-op; both shapes are valid.
        if _read_grandparent_pid() is None:
            assert threads == []
            return
        assert len(threads) == 1
        watcher_thread = threads[0].thread
        deadline = threading.Event()
        deadline.wait(timeout=_PARENT_POLL_INTERVAL_SECONDS + 1.0)
        assert watcher_thread.is_alive(), "Grandparent watcher exited unexpectedly during poll cycle"
