"""Unit tests for config CLI command helper functions."""

import json
from pathlib import Path

import pluggy
import pytest
import tomlkit
from click.testing import CliRunner

from imbue.mng.cli.config import _flatten_config
from imbue.mng.cli.config import _format_value_for_display
from imbue.mng.cli.config import _get_nested_value
from imbue.mng.cli.config import _parse_value
from imbue.mng.cli.config import _unset_nested_value
from imbue.mng.cli.config import config
from imbue.mng.cli.config import load_config_file_tomlkit
from imbue.mng.cli.config import save_config_file
from imbue.mng.cli.config import set_nested_value
from imbue.mng.errors import ConfigKeyNotFoundError


def test_parse_value_parses_true_as_boolean() -> None:
    result = _parse_value("true")
    assert result is True
    assert isinstance(result, bool)


def test_parse_value_parses_false_as_boolean() -> None:
    result = _parse_value("false")
    assert result is False
    assert isinstance(result, bool)


def test_parse_value_parses_integer() -> None:
    result = _parse_value("42")
    assert result == 42
    assert isinstance(result, int)


def test_parse_value_parses_float() -> None:
    result = _parse_value("3.14")
    assert result == 3.14
    assert isinstance(result, float)


def test_parse_value_parses_array() -> None:
    result = _parse_value('["a", "b", "c"]')
    assert result == ["a", "b", "c"]


def test_parse_value_parses_object() -> None:
    result = _parse_value('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_value_returns_string_for_plain_text() -> None:
    result = _parse_value("hello world")
    assert result == "hello world"
    assert isinstance(result, str)


def test_parse_value_returns_string_for_unquoted_string() -> None:
    result = _parse_value("my-prefix-")
    assert result == "my-prefix-"
    assert isinstance(result, str)


def test_format_value_for_display_formats_true() -> None:
    result = _format_value_for_display(True)
    assert result == "true"


def test_format_value_for_display_formats_false() -> None:
    result = _format_value_for_display(False)
    assert result == "false"


def test_format_value_for_display_formats_string_directly() -> None:
    result = _format_value_for_display("hello")
    assert result == "hello"


def test_format_value_for_display_formats_number_as_json() -> None:
    result = _format_value_for_display(42)
    assert result == "42"


def test_format_value_for_display_formats_list_as_json() -> None:
    result = _format_value_for_display(["a", "b"])
    assert result == '["a", "b"]'


def test_get_nested_value_retrieves_top_level_key() -> None:
    data = {"prefix": "mng-"}
    result = _get_nested_value(data, "prefix")
    assert result == "mng-"


def test_get_nested_value_retrieves_nested_key() -> None:
    data = {"commands": {"create": {"connect": False}}}
    result = _get_nested_value(data, "commands.create.connect")
    assert result is False


def test_get_nested_value_raises_keyerror_for_missing_key() -> None:
    data = {"prefix": "mng-"}
    with pytest.raises(ConfigKeyNotFoundError, match="nonexistent"):
        _get_nested_value(data, "nonexistent")


def test_get_nested_value_raises_keyerror_for_missing_nested_key() -> None:
    data = {"commands": {"create": {}}}
    with pytest.raises(ConfigKeyNotFoundError, match="nonexistent"):
        _get_nested_value(data, "commands.create.nonexistent")


def test_set_nested_value_sets_top_level_key() -> None:
    doc = tomlkit.document()
    set_nested_value(doc, "prefix", "my-")
    assert doc["prefix"] == "my-"


def test_set_nested_value_sets_nested_key() -> None:
    doc = tomlkit.document()
    set_nested_value(doc, "commands.create.connect", False)
    # Convert to dict for assertions since tomlkit types are opaque to type checker
    data = doc.unwrap()
    assert data["commands"]["create"]["connect"] is False


def test_set_nested_value_creates_intermediate_tables() -> None:
    doc = tomlkit.document()
    set_nested_value(doc, "a.b.c.d", "value")
    data = doc.unwrap()
    assert data["a"]["b"]["c"]["d"] == "value"


def test_set_nested_value_overwrites_existing_value() -> None:
    doc = tomlkit.document()
    doc["prefix"] = "old-"
    set_nested_value(doc, "prefix", "new-")
    assert doc["prefix"] == "new-"


def test_unset_nested_value_removes_top_level_key() -> None:
    doc = tomlkit.document()
    doc["prefix"] = "mng-"
    result = _unset_nested_value(doc, "prefix")
    assert result is True
    assert "prefix" not in doc


def test_unset_nested_value_removes_nested_key() -> None:
    doc = tomlkit.document()
    doc["commands"] = {"create": {"connect": False, "other": True}}
    result = _unset_nested_value(doc, "commands.create.connect")
    assert result is True
    data = doc.unwrap()
    assert "connect" not in data["commands"]["create"]
    assert data["commands"]["create"]["other"] is True


def test_unset_nested_value_returns_false_for_missing_key() -> None:
    doc = tomlkit.document()
    result = _unset_nested_value(doc, "nonexistent")
    assert result is False


def test_unset_nested_value_returns_false_for_missing_nested_key() -> None:
    doc = tomlkit.document()
    doc["commands"] = {"create": {}}
    result = _unset_nested_value(doc, "commands.create.nonexistent")
    assert result is False


def test_flatten_config_flattens_simple_dict() -> None:
    config = {"prefix": "mng-", "pager": "less"}
    result = _flatten_config(config)
    assert ("prefix", "mng-") in result
    assert ("pager", "less") in result


def test_flatten_config_flattens_nested_dict() -> None:
    config = {"commands": {"create": {"connect": False}}}
    result = _flatten_config(config)
    assert ("commands.create.connect", False) in result


def test_flatten_config_flattens_deeply_nested_dict() -> None:
    config = {"a": {"b": {"c": {"d": "value"}}}}
    result = _flatten_config(config)
    assert ("a.b.c.d", "value") in result


def test_flatten_config_returns_empty_list_for_empty_dict() -> None:
    result = _flatten_config({})
    assert result == []


def test_load_config_file_tomlkit_returns_empty_document_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "nonexistent.toml"
    doc = load_config_file_tomlkit(missing_path)
    assert len(doc) == 0


def test_load_config_file_tomlkit_loads_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.toml"
    config_path.write_text('prefix = "test-"\n')
    doc = load_config_file_tomlkit(config_path)
    assert doc["prefix"] == "test-"


def test_save_config_file_creates_parent_directories(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "dir" / "test.toml"
    doc = tomlkit.document()
    doc["prefix"] = "test-"
    save_config_file(config_path, doc)
    assert config_path.exists()
    assert config_path.read_text() == 'prefix = "test-"\n'


def test_save_config_file_preserves_formatting(tmp_path: Path) -> None:
    config_path = tmp_path / "test.toml"
    doc = tomlkit.document()
    doc.add(tomlkit.comment("This is a comment"))
    doc["prefix"] = "test-"
    save_config_file(config_path, doc)
    content = config_path.read_text()
    assert "# This is a comment" in content
    assert 'prefix = "test-"' in content


# =============================================================================
# CLI command invocation tests
# =============================================================================


def test_config_help_exits_zero(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config --help` works and exits 0."""
    result = cli_runner.invoke(
        config,
        ["--help"],
        obj=plugin_manager,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "config" in result.output.lower()


def test_config_get_nonexistent_key(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config get` with a nonexistent key returns error."""
    result = cli_runner.invoke(
        config,
        ["get", "this.key.does.not.exist.anywhere"],
        obj=plugin_manager,
        catch_exceptions=True,
    )
    assert result.exit_code != 0


def test_config_list_outputs_something(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config list` produces output."""
    result = cli_runner.invoke(
        config,
        ["list"],
        obj=plugin_manager,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # Should contain some configuration information
    assert len(result.output.strip()) > 0


# =============================================================================
# Additional helper function tests
# =============================================================================


def test_flatten_config_with_mixed_nested_and_flat_keys() -> None:
    """Test _flatten_config with a mix of flat and nested keys."""
    config_data = {
        "prefix": "mng-",
        "commands": {
            "create": {"connect": True, "name_style": "english"},
            "destroy": {"force": False},
        },
        "logging": {"console_level": "INFO"},
    }
    result = _flatten_config(config_data)
    keys = [k for k, _ in result]
    assert "prefix" in keys
    assert "commands.create.connect" in keys
    assert "commands.create.name_style" in keys
    assert "commands.destroy.force" in keys
    assert "logging.console_level" in keys


def test_format_value_for_display_with_dict() -> None:
    """Test _format_value_for_display with a dict value."""
    result = _format_value_for_display({"key": "value"})
    assert '"key"' in result
    assert '"value"' in result


def test_format_value_for_display_with_empty_list() -> None:
    """Test _format_value_for_display with an empty list."""
    result = _format_value_for_display([])
    assert result == "[]"


def test_format_value_for_display_with_integer() -> None:
    """Test _format_value_for_display with an integer."""
    result = _format_value_for_display(100)
    assert result == "100"


def test_save_and_load_config_file_roundtrip(tmp_path: Path) -> None:
    """Test that save_config_file and load_config_file_tomlkit roundtrip correctly."""
    config_path = tmp_path / "roundtrip.toml"

    # Create a document with various value types
    doc = tomlkit.document()
    doc["prefix"] = "my-prefix-"
    doc["enabled"] = True
    doc["count"] = 42

    # Create a nested table
    commands = tomlkit.table()
    create_opts = tomlkit.table()
    create_opts["connect"] = False
    create_opts["name_style"] = "english"
    commands["create"] = create_opts
    doc["commands"] = commands

    # Save
    save_config_file(config_path, doc)
    assert config_path.exists()

    # Load
    loaded_doc = load_config_file_tomlkit(config_path)
    loaded_data = loaded_doc.unwrap()

    assert loaded_data["prefix"] == "my-prefix-"
    assert loaded_data["enabled"] is True
    assert loaded_data["count"] == 42
    assert loaded_data["commands"]["create"]["connect"] is False
    assert loaded_data["commands"]["create"]["name_style"] == "english"


def test_config_list_json_format(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config list --format json` produces valid JSON."""
    result = cli_runner.invoke(
        config,
        ["list", "--format", "json"],
        obj=plugin_manager,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    data = json.loads(result.output.strip())
    assert "config" in data


def test_config_path_outputs_paths(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config path` produces output about config paths."""
    result = cli_runner.invoke(
        config,
        ["path"],
        obj=plugin_manager,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "user" in result.output.lower()


def test_config_path_scope_user(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config path --scope user` shows user config path."""
    result = cli_runner.invoke(
        config,
        ["path", "--scope", "user"],
        obj=plugin_manager,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert len(result.output.strip()) > 0


def test_config_get_existing_key(
    cli_runner: CliRunner,
    plugin_manager: pluggy.PluginManager,
) -> None:
    """Test that `config get prefix` returns the prefix value."""
    result = cli_runner.invoke(
        config,
        ["get", "prefix"],
        obj=plugin_manager,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert len(result.output.strip()) > 0
