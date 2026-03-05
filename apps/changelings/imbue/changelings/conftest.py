"""Conftest for changelings package-level tests (e.g. end-to-end release tests).

The deployed_test_coder fixture is module-scoped so that multiple tests
sharing it reuse a single deployed agent, avoiding redundant deploy cycles.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest


def _clean_env() -> dict[str, str]:
    """Build an environment dict for subprocesses that strips pytest markers.

    mng refuses to run when PYTEST_CURRENT_TEST is set (safety check to
    prevent tests from accidentally using real mng state). We strip it
    so that our end-to-end subprocess calls work against the real system.
    """
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def run_mng(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    """Run a `uv run mng` command and return the result."""
    return subprocess.run(
        ["uv", "run", "mng", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_env(),
    )


def run_changeling(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Run a `uv run changeling` command and return the result."""
    return subprocess.run(
        ["uv", "run", "changeling", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_env(),
    )


def parse_mng_list_json(stdout: str) -> list[dict[str, object]]:
    """Extract agent records from mng list --json stdout.

    The stdout may contain non-JSON lines (e.g. SSH error tracebacks)
    mixed with the JSON. We find the first line starting with '{' and
    parse from there.
    """
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                return list(data.get("agents", []))
            except json.JSONDecodeError:
                continue
    return []


def find_agent(agent_name: str) -> dict[str, object] | None:
    """Find an agent by name, returning its full record or None."""
    result = run_mng(
        "list",
        "--include",
        f'name == "{agent_name}"',
        "--json",
        "--provider",
        "local",
    )
    if result.returncode != 0:
        return None
    agents = parse_mng_list_json(result.stdout)
    if agents:
        return agents[0]
    return None


def extract_response(exec_result: subprocess.CompletedProcess[str]) -> str:
    """Extract the model response from mng exec output.

    Filters out mng's "Command succeeded/failed" status lines,
    returning only the first line of actual model output.
    """
    response_lines = [
        line for line in exec_result.stdout.strip().splitlines() if line and not line.startswith("Command ")
    ]
    assert len(response_lines) >= 1, f"No response from model: {exec_result.stdout!r}"
    return response_lines[0]


def _cleanup_agent(agent_name: str) -> None:
    """Destroy an agent and clean up its changeling directory."""
    agent = find_agent(agent_name)
    agent_id = str(agent["id"]) if agent else None

    run_mng("destroy", agent_name, "--force", timeout=30.0)

    if agent_id:
        changeling_dir = Path.home() / ".changelings" / agent_id
        if changeling_dir.exists():
            shutil.rmtree(changeling_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def deployed_test_coder() -> Generator[dict[str, object], None, None]:
    """Deploy a test-coder changeling and yield its agent record.

    Module-scoped so all tests in the module share a single deployed agent,
    avoiding redundant deploy cycles (~30s each). Handles deployment and
    cleanup so individual tests only need to exercise the deployed agent.
    """
    agent_name = f"e2e-test-{uuid4().hex}"

    deploy_result = run_changeling(
        "deploy",
        "--agent-type",
        "test-coder",
        "--name",
        agent_name,
        "--provider",
        "local",
        "--no-self-deploy",
    )
    assert deploy_result.returncode == 0, (
        f"Deploy failed:\nstdout: {deploy_result.stdout}\nstderr: {deploy_result.stderr}"
    )

    agent = find_agent(agent_name)
    assert agent is not None, f"Agent {agent_name} not found in mng list"

    try:
        yield agent
    finally:
        _cleanup_agent(agent_name)
