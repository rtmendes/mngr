import os
import subprocess
from collections.abc import Callable
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Browser
from playwright.sync_api import Playwright
from playwright.sync_api import sync_playwright

from imbue.minds_workspace_server.agent_manager import AgentManager
from imbue.minds_workspace_server.ws_broadcaster import WebSocketBroadcaster


@pytest.fixture
def playwright() -> Generator[Playwright, None, None]:
    """Override pytest-playwright's session-scoped playwright to function scope.

    The upstream fixture (pytest_playwright.pytest_playwright.playwright)
    is session-scoped and torn down at pytest session end; its teardown
    reaps the playwright-node driver subprocess. That teardown runs AFTER
    mngr's autouse `session_cleanup` fixture
    (libs/mngr/imbue/mngr/conftest.py) checks for leaked child processes,
    so in offload release batches that mix workspace-server e2e tests with
    other mngr tests, the still-alive node driver trips the cleanup
    assertion and cascades into teardown errors for every sibling test
    in the batch (test_install.py, test_help.py, Vultr's test_release_vultr
    all show up as "PID X: MainThread - .../playwright/driver/node ... run-driver"
    leaks).

    Making playwright per-test guarantees each test's driver exits inside
    its own teardown before any session-level check runs. Cost: a few
    hundred ms per test to re-spawn the node driver -- acceptable for the
    small e2e suite and avoids a brittle race with external fixture
    ordering.
    """
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture
def browser(launch_browser: Callable[[], Browser]) -> Generator[Browser, None, None]:
    """Override pytest-playwright's session-scoped browser to function scope.

    Same rationale as the playwright fixture above: upstream's session
    scope means chrome-headless-shell outlives the per-test teardown,
    and mngr's session_cleanup autouse catches it as a leak. Per-test
    browser closes synchronously, reaping chrome before any session-
    level check runs.
    """
    browser_instance = launch_browser()
    yield browser_instance
    browser_instance.close()


@pytest.fixture
def broadcaster() -> WebSocketBroadcaster:
    return WebSocketBroadcaster()


@pytest.fixture
def agent_manager(broadcaster: WebSocketBroadcaster, monkeypatch: pytest.MonkeyPatch) -> AgentManager:
    """Create an AgentManager without starting the observe subprocess."""
    monkeypatch.setenv("MNGR_AGENT_ID", "test-agent-id")
    monkeypatch.setenv("MNGR_AGENT_WORK_DIR", "/tmp/test-work")
    return AgentManager.build(broadcaster)


@pytest.fixture
def git_work_dir(tmp_path: Path) -> Path:
    """Create a minimal git repository for tests that need a real git work directory."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    return tmp_path
