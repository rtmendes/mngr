"""Ratchet tests for the mngr_forward plugin.

Mirrors the standard rule set used in other ``libs/mngr_*/`` plugins so the
plugin can't accumulate the prevented anti-patterns over time.
"""

from pathlib import Path

import pytest
from inline_snapshot import snapshot

from imbue.imbue_common.ratchet_testing import standard_ratchet_checks as rc
from imbue.imbue_common.ratchet_testing.ratchets import check_no_ruff_errors
from imbue.imbue_common.ratchet_testing.ratchets import check_no_type_errors

_DIR = Path(__file__).parent.parent.parent

pytestmark = pytest.mark.xdist_group(name="ratchets")


def test_no_type_errors() -> None:
    check_no_type_errors(_DIR)


def test_no_ruff_errors() -> None:
    check_no_ruff_errors(_DIR)


def test_prevent_silent_decode_error_catches() -> None:
    rc.check_silent_decode_error_catches(_DIR, snapshot(0))


def test_prevent_getattr() -> None:
    rc.check_getattr(_DIR, snapshot(0))


def test_prevent_setattr() -> None:
    rc.check_setattr(_DIR, snapshot(0))


def test_prevent_exit_stack() -> None:
    rc.check_exit_stack(_DIR, snapshot(0))


def test_prevent_hardcoded_claude_dir() -> None:
    rc.check_hardcoded_claude_dir(_DIR, snapshot(0))


def test_prevent_hardcoded_guarded_binary() -> None:
    rc.check_hardcoded_guarded_binary(_DIR, snapshot(0))


def test_prevent_bare_except() -> None:
    rc.check_bare_except(_DIR, snapshot(0))


def test_prevent_inline_imports() -> None:
    rc.check_inline_imports(_DIR, snapshot(0))


def test_prevent_relative_imports() -> None:
    rc.check_relative_imports(_DIR, snapshot(0))


def test_prevent_dataclasses_import() -> None:
    rc.check_dataclasses_import(_DIR, snapshot(0))


def test_prevent_yaml_usage() -> None:
    rc.check_yaml_usage(_DIR, snapshot(0))


def test_prevent_init_docstrings() -> None:
    rc.check_init_docstrings(_DIR, snapshot(0))
