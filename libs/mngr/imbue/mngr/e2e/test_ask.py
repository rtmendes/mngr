"""Tests for the mngr ask command with the Claude plugin."""

import json

import pytest

from imbue.mngr.e2e.conftest import E2eSession
from imbue.skitwright.expect import expect

_ASK_TIMEOUT = 120.0


@pytest.mark.release
@pytest.mark.tmux
@pytest.mark.timeout(120)
def test_ask_simple_query(e2e: E2eSession) -> None:
    result = e2e.run(
        'mngr ask "just say hi" --format json',
        comment="Ask Claude a simple question via mngr ask",
        timeout=_ASK_TIMEOUT,
    )
    expect(result).to_succeed()
    parsed = json.loads(result.stdout)
    assert len(parsed["response"].strip()) > 0, f"Expected non-empty response, got: {parsed['response']!r}"
