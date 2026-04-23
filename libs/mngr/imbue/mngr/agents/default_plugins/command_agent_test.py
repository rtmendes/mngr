from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path

import pytest

from imbue.mngr.agents.default_plugins.command_agent import CommandAgent
from imbue.mngr.agents.default_plugins.command_agent import CommandAgentConfig
from imbue.mngr.config.data_types import MngrContext
from imbue.mngr.errors import UserInputError
from imbue.mngr.hosts.host import Host
from imbue.mngr.primitives import AgentId
from imbue.mngr.primitives import AgentName
from imbue.mngr.primitives import AgentTypeName
from imbue.mngr.primitives import CommandString


def _make_command_agent(
    host: Host,
    mngr_ctx: MngrContext,
    tmp_path: Path,
    agent_config: CommandAgentConfig | None = None,
) -> CommandAgent:
    """Create a CommandAgent with a real local host for testing."""
    work_dir = tmp_path / f"work-{str(AgentId.generate().get_uuid())[:8]}"
    work_dir.mkdir()

    if agent_config is None:
        agent_config = CommandAgentConfig()

    return CommandAgent.model_construct(
        id=AgentId.generate(),
        name=AgentName("test-command"),
        agent_type=AgentTypeName("command"),
        work_dir=work_dir,
        create_time=datetime.now(timezone.utc),
        host_id=host.id,
        mngr_ctx=mngr_ctx,
        agent_config=agent_config,
        host=host,
    )


def test_assemble_command_uses_override_as_base_and_appends_args(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """command_override is used as the base command; cli_args and agent_args are still appended (matches BaseAgent)."""
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path)
    override = CommandString("echo from-override")
    cmd = agent.assemble_command(local_host, agent_args=("extra",), command_override=override)
    assert cmd == CommandString("echo from-override extra")


def test_assemble_command_override_alone_returns_override_verbatim(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """command_override with no agent_args or cli_args returns the override unchanged."""
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path)
    override = CommandString("echo from-override")
    cmd = agent.assemble_command(local_host, agent_args=(), command_override=override)
    assert cmd == override


def test_assemble_command_joins_agent_args_with_spaces(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """Non-empty agent_args are joined with spaces into a CommandString."""
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path)
    cmd = agent.assemble_command(local_host, agent_args=("sleep", "42"), command_override=None)
    assert cmd == CommandString("sleep 42")


def test_assemble_command_raises_when_no_args_and_no_override(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """Empty agent_args with no override and no config.command produces a helpful UserInputError."""
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path)
    with pytest.raises(UserInputError, match=r"has no command configured"):
        agent.assemble_command(local_host, agent_args=(), command_override=None)


def test_assemble_command_uses_agent_config_command(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """agent_config.command is used when agent_args is empty."""
    config = CommandAgentConfig(command=CommandString("python -m http.server 8080"))
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path, agent_config=config)
    cmd = agent.assemble_command(local_host, agent_args=(), command_override=None)
    assert cmd == CommandString("python -m http.server 8080")


def test_assemble_command_concatenates_config_command_and_agent_args(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """agent_config.command is prepended to agent_args (matches BaseAgent.assemble_command)."""
    config = CommandAgentConfig(command=CommandString("python -m http.server"))
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path, agent_config=config)
    cmd = agent.assemble_command(local_host, agent_args=("--bind", "0.0.0.0"), command_override=None)
    assert cmd == CommandString("python -m http.server --bind 0.0.0.0")


def test_assemble_command_inserts_cli_args_between_command_and_agent_args(
    local_host: Host,
    temp_mngr_ctx: MngrContext,
    tmp_path: Path,
) -> None:
    """agent_config.cli_args sit between the base command and agent_args (matches BaseAgent.assemble_command)."""
    config = CommandAgentConfig(
        command=CommandString("python -m http.server"),
        cli_args=("--bind", "0.0.0.0"),
    )
    agent = _make_command_agent(local_host, temp_mngr_ctx, tmp_path, agent_config=config)
    cmd = agent.assemble_command(local_host, agent_args=("--extra",), command_override=None)
    assert cmd == CommandString("python -m http.server --bind 0.0.0.0 --extra")
