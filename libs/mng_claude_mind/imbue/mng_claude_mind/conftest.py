import os
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from imbue.mng.providers.ssh_host_setup import load_resource_script
from imbue.mng.utils.plugin_testing import register_plugin_test_fixtures
from imbue.mng.utils.testing import init_git_repo_with_config
from imbue.mng_llm.conftest import (
    create_mind_conversations_table_in_test_db as create_mind_conversations_table_in_test_db,
)
from imbue.mng_llm.conftest import create_test_llm_db as create_test_llm_db
from imbue.mng_llm.conftest import write_conversation_to_db as write_conversation_to_db
from imbue.mng_llm.conftest import write_minds_settings_toml as write_minds_settings_toml
from imbue.mng_llm.provisioning import MIND_CONVERSATIONS_TABLE_SQL as MIND_CONVERSATIONS_TABLE_SQL
from imbue.mng_llm.provisioning import load_llm_resource
from imbue.mng_mind.conftest import StubCommandResult as StubCommandResult
from imbue.mng_mind.conftest import StubHost as StubHost

register_plugin_test_fixtures(globals())


@pytest.fixture(autouse=True)
def _reset_loguru() -> Generator[None, None, None]:
    """Reset loguru handlers before and after each test to prevent handler leakage."""
    logger.remove()
    yield
    logger.remove()


@pytest.fixture(autouse=True)
def _isolate_tmux_server(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Give each test its own isolated tmux server.

    Overrides the version from plugin_testing to use subprocess.run for cleanup
    instead of ConcurrencyGroup, which raises ProcessSetupError when no tmux
    server was started (common for unit tests that don't create tmux sessions).
    """
    tmux_tmpdir = Path(tempfile.mkdtemp(prefix="mng-tmux-", dir="/tmp"))
    monkeypatch.setenv("TMUX_TMPDIR", str(tmux_tmpdir))
    monkeypatch.delenv("TMUX", raising=False)

    yield

    tmux_tmpdir_str = str(tmux_tmpdir)
    assert tmux_tmpdir_str.startswith("/tmp/mng-tmux-"), (
        f"TMUX_TMPDIR safety check failed! Expected /tmp/mng-tmux-* path but got: {tmux_tmpdir_str}. "
        "Refusing to run 'tmux kill-server' to avoid killing the real tmux server."
    )
    socket_path = Path(tmux_tmpdir_str) / f"tmux-{os.getuid()}" / "default"
    kill_env = os.environ.copy()
    kill_env.pop("TMUX", None)
    kill_env["TMUX_TMPDIR"] = tmux_tmpdir_str
    try:
        subprocess.run(
            ["tmux", "-S", str(socket_path), "kill-server"],
            capture_output=True,
            env=kill_env,
        )
    except OSError:
        logger.debug("tmux kill-server failed (expected when no tmux session was started)")
    shutil.rmtree(tmux_tmpdir, ignore_errors=True)


class _ShellCommandResult:
    """Result of a shell command execution, matching the interface expected by provisioning code."""

    def __init__(self, *, success: bool, stdout: str, stderr: str) -> None:
        self.success = success
        self.stdout = stdout
        self.stderr = stderr


class LocalShellHost:
    """Test double that executes commands via subprocess on the local filesystem."""

    def __init__(self, host_dir: Path) -> None:
        self.host_dir = host_dir

    def execute_command(self, command: str, **kwargs: Any) -> _ShellCommandResult:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, env=os.environ)
        return _ShellCommandResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def read_text_file(self, path: Path) -> str:
        return path.read_text()

    def write_text_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def write_file(self, path: Path, content: bytes, mode: str = "0644") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.chmod(path, int(mode, 8))


@pytest.fixture()
def local_shell_host(temp_host_dir: Path) -> LocalShellHost:
    """Provide a LocalShellHost backed by the temp host directory."""
    return LocalShellHost(host_dir=temp_host_dir)


class ChatScriptEnv:
    """Environment for running the chat.sh script in tests."""

    def __init__(self, temp_host_dir: Path) -> None:
        self.agent_state_dir = temp_host_dir / "agents" / "test-agent"

        commands_dir = self.agent_state_dir / "commands"
        commands_dir.mkdir(parents=True)

        self.chat_script = commands_dir / "chat.sh"
        self.chat_script.write_text(load_llm_resource("chat.sh"))
        os.chmod(self.chat_script, 0o755)

        mng_log_path = commands_dir / "mng_log.sh"
        mng_log_path.write_text(load_resource_script("mng_log.sh"))
        os.chmod(mng_log_path, 0o755)
        self.messages_dir = self.agent_state_dir / "events" / "messages"
        self.messages_dir.mkdir(parents=True)

        self.llm_data_dir = self.agent_state_dir / "llm_data"
        self.llm_data_dir.mkdir(parents=True)
        self.llm_db_path = self.llm_data_dir / "logs.db"
        create_mind_conversations_table_in_test_db(self.llm_db_path)

        self.work_dir = temp_host_dir / "work"
        self.work_dir.mkdir(parents=True)

        self.env = os.environ.copy()
        self.env["MNG_AGENT_STATE_DIR"] = str(self.agent_state_dir)
        self.env["MNG_HOST_DIR"] = str(temp_host_dir)
        self.env["MNG_AGENT_WORK_DIR"] = str(self.work_dir)
        self.env["LLM_USER_PATH"] = str(self.llm_data_dir)

    def set_default_model(self, model: str) -> None:
        """Write the chat model to minds.toml in the work dir."""
        (self.work_dir / "minds.toml").write_text(f'[chat]\nmodel = "{model}"\n')

    def run(self, *args: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
        """Run chat.sh with the given arguments."""
        return subprocess.run(
            [str(self.chat_script), *args],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=timeout,
        )


@pytest.fixture()
def chat_env(temp_host_dir: Path) -> ChatScriptEnv:
    """Provide a ChatScriptEnv for testing chat.sh."""
    return ChatScriptEnv(temp_host_dir)


@pytest.fixture()
def stub_host() -> StubHost:
    """Provide a fresh StubHost instance."""
    return StubHost()


@pytest.fixture()
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with an initial commit and local git config."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    init_git_repo_with_config(repo_dir)
    return repo_dir


def assert_conversation_exists_in_db(db_path: Path, conversation_id: str) -> None:
    """Assert that a conversation record exists in the mind_conversations table."""
    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT conversation_id FROM mind_conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
    assert len(rows) == 1, f"Expected conversation {conversation_id} in DB, found {len(rows)} rows"
