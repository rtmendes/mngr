"""End-to-end test for the minds forwarding server using Playwright.

Starts the forwarding server, creates an agent from the forever-claude-template
repo, and waits for a signal file before tearing down. This allows interactive
inspection of the running system.

Run from the repo root:
    just test apps/minds/test_forwarding_server_e2e.py::test_create_agent_e2e

Run headed (browser visible for interactive debugging):
    HEADED=1 just test apps/minds/test_forwarding_server_e2e.py::test_create_agent_e2e

The test waits for /tmp/minds-e2e-done to exist before tearing down.
Create this file to signal the test to finish:
    touch /tmp/minds-e2e-done

The test removes /tmp/minds-e2e-done on startup so it always waits fresh.
"""

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import dotenv
import pytest
import uvicorn
from loguru import logger
from playwright.sync_api import sync_playwright

from imbue.minds.config.data_types import MindPaths
from imbue.minds.forwarding_server.agent_creator import AgentCreator
from imbue.minds.forwarding_server.app import create_forwarding_server
from imbue.minds.forwarding_server.auth import FileAuthStore
from imbue.minds.forwarding_server.backend_resolver import MngrCliBackendResolver
from imbue.minds.forwarding_server.backend_resolver import MngrStreamManager
from imbue.minds.primitives import OneTimeCode

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_REPO = Path.home() / "project" / "forever-claude-template"
_SIGNAL_FILE = Path("/tmp/minds-e2e-done")
_AGENT_NAME = "forever"


def _configure_logging() -> None:
    """Set up trace-level logging so all server internals are visible."""
    logger.remove()
    logger.add(sys.stderr, level="TRACE", format="{time:HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}")


def _load_env() -> None:
    """Load environment variables from the repo root .env file."""
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        dotenv.load_dotenv(env_file)


def _find_free_port() -> int:
    """Find and return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_signal_file(path: Path, poll_interval: float = 1.0) -> None:
    """Block until the signal file exists."""
    while not path.exists():
        time.sleep(poll_interval)


def _destroy_agent(agent_name: str) -> None:
    """Destroy an agent by name, ignoring errors if it doesn't exist."""
    try:
        subprocess.run(
            ["uv", "run", "mngr", "destroy", agent_name, "--force"],
            input="y\n",
            capture_output=True,
            timeout=30,
            text=True,
            cwd=_REPO_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


class ForwardingServerFixture:
    """Manages a forwarding server lifecycle for testing."""

    def __init__(self, tmp_dir: Path) -> None:
        self.host = "127.0.0.1"
        self.port = _find_free_port()
        self.code = OneTimeCode("test-code-for-e2e-12345")
        self.tmp_dir = tmp_dir
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._stream_manager: MngrStreamManager | None = None

    @property
    def login_url(self) -> str:
        return f"http://{self.host}:{self.port}/login?one_time_code={self.code}"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """Start the forwarding server with agent discovery in a background thread."""
        paths = MindPaths(data_dir=self.tmp_dir)
        auth_store = FileAuthStore(data_directory=paths.auth_dir)
        auth_store.add_one_time_code(code=self.code)

        backend_resolver = MngrCliBackendResolver()
        self._stream_manager = MngrStreamManager(resolver=backend_resolver)
        agent_creator = AgentCreator(paths=paths)

        app = create_forwarding_server(
            auth_store=auth_store,
            backend_resolver=backend_resolver,
            http_client=None,
            agent_creator=agent_creator,
        )

        self._stream_manager.start()

        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="trace")
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        for _ in range(50):
            try:
                with socket.create_connection((self.host, self.port), timeout=0.1):
                    logger.info("Forwarding server started on {}:{}", self.host, self.port)
                    return
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)

        raise TimeoutError("Forwarding server did not start within 5 seconds")

    def stop(self) -> None:
        """Signal the server to shut down."""
        if self._stream_manager is not None:
            self._stream_manager.stop()
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


def _on_console(msg: object) -> None:
    """Log browser console messages."""
    logger.info("[browser console] {}", msg)


def _on_response(response: object) -> None:
    """Log browser network responses."""
    url = getattr(response, "url", "?")
    status = getattr(response, "status", "?")
    if "/api/" in str(url) or "event" in str(url).lower():
        logger.debug("[browser response] {} {}", status, url)


@pytest.mark.release
def test_create_agent_e2e(tmp_path: Path) -> None:
    """Create an agent from the forever-claude-template and verify it runs.

    After creation, waits for /tmp/minds-e2e-done before tearing down,
    allowing interactive inspection of the running agent.
    """
    _configure_logging()
    _load_env()

    os.environ["MIND_NAME"] = _AGENT_NAME

    _SIGNAL_FILE.unlink(missing_ok=True)
    _destroy_agent(_AGENT_NAME)

    server = ForwardingServerFixture(tmp_path)
    server.start()

    headed = os.environ.get("HEADED", "0") == "1"
    slow_mo = int(os.environ.get("SLOW_MO", "0"))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed, slow_mo=slow_mo)
            try:
                page = browser.new_page()
                page.on("console", _on_console)
                page.on("response", _on_response)

                # Authenticate
                logger.info("Authenticating at {}", server.login_url)
                page.goto(server.login_url)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_url(re.compile(r"/$|/create"), timeout=5000)
                logger.info("Authenticated, on landing page: {}", page.url)

                # Navigate to create page
                page.goto(f"{server.base_url}/create")
                page.wait_for_load_state("domcontentloaded")
                logger.info("On create page: {}", page.url)

                # Fill out the create form
                page.fill("#agent_name", _AGENT_NAME)
                page.fill("#git_url", str(_TEMPLATE_REPO))
                page.fill("#branch", "")
                page.select_option("#launch_mode", "LOCAL")
                logger.info("Form filled, submitting...")

                # Submit the form
                page.click('button[type="submit"]')
                logger.info("Form submitted, URL: {}", page.url)

                # Should redirect to creating page with logs
                page.wait_for_url(re.compile(r"/creating/"), timeout=10000)
                logger.info("On creating page: {}", page.url)

                # Wait for creation to complete.
                # The creating page JS receives SSE events and redirects when done.
                logger.info("Waiting for agent creation to complete (up to 5 min)...")
                page.wait_for_url(
                    re.compile(r"/agents/"),
                    timeout=300000,
                )

                agent_url = page.url
                logger.info("Agent created! URL: {}", agent_url)
                logger.info("Server: {}", server.base_url)
                logger.info("Waiting for signal file: {}", _SIGNAL_FILE)
                logger.info("Create it to finish the test:  touch {}", _SIGNAL_FILE)

                # Wait for the signal file before tearing down
                _wait_for_signal_file(_SIGNAL_FILE)

                logger.info("Signal received, tearing down...")

            finally:
                browser.close()
    finally:
        _destroy_agent(_AGENT_NAME)
        server.stop()
        _SIGNAL_FILE.unlink(missing_ok=True)
