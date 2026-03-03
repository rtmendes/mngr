"""Unit tests for the mng-changeling-chat CLI module."""

from click.testing import CliRunner

from imbue.mng_changeling_chat.cli import ChatCliOptions
from imbue.mng_changeling_chat.cli import chat


def test_chat_command_help_shows_all_options() -> None:
    """Verify that the chat --help output contains all expected options."""
    runner = CliRunner()
    result = runner.invoke(chat, ["--help"])

    assert result.exit_code == 0
    assert "--new" in result.output
    assert "--last" in result.output
    assert "--conversation" in result.output
    assert "--allow-unknown-host" in result.output
    assert "--start" in result.output
    assert "AGENT" in result.output


def test_chat_cli_options_has_all_required_fields() -> None:
    """Verify ChatCliOptions declares all expected field types."""
    annotations = ChatCliOptions.__annotations__
    assert annotations["agent"] == (str | None)
    assert annotations["new"] is bool
    assert annotations["last"] is bool
    assert annotations["conversation"] == (str | None)
    assert annotations["start"] is bool
    assert annotations["allow_unknown_host"] is bool
