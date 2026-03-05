"""End-to-end test for changeling deployment and chat using the test-coder agent type.

Deploys a real changeling locally using the test-coder agent type (which uses
the echo model instead of real LLMs), verifies the full pipeline works, and
cleans up. No API keys are required.

The echo model's env-var-based customization (LLM_ECHO_RESPONSE and
LLM_ECHO_RESPONSES_FILE) is thoroughly unit-tested in libs/llm_echo/llm_echo_test.py.
This test focuses on verifying the deployment pipeline and that the echo model
is correctly installed and configured in the changeling environment.
"""

from pathlib import Path

import pytest

from imbue.changelings.testing import extract_response
from imbue.changelings.testing import run_mng


@pytest.mark.release
@pytest.mark.timeout(120)
def test_deploy_test_coder_and_verify_echo_model(deployed_test_coder: dict[str, object]) -> None:
    """Deploy a test-coder changeling and verify the echo model works end-to-end.

    Verifies:
    1. The changeling was deployed successfully (via the fixture)
    2. The echo model is installed and responds correctly via mng exec
    3. The chat settings are configured with model = "echo"
    4. The env-var-based response override works in the agent environment
    """
    agent_name = str(deployed_test_coder["name"])

    # Verify the echo model returns the expected default response
    test_message = "Hello from end-to-end test"
    exec_result = run_mng("exec", agent_name, f'llm -m echo "{test_message}"')
    assert exec_result.returncode == 0, f"llm echo failed:\nstdout: {exec_result.stdout}\nstderr: {exec_result.stderr}"
    assert extract_response(exec_result) == f"Echo: {test_message}"

    # Verify the chat settings have the echo model configured
    work_dir = str(deployed_test_coder["work_dir"])
    settings_path = Path(work_dir) / ".changelings" / "settings.toml"
    assert settings_path.exists(), f"Settings file not found at {settings_path}"
    settings_content = settings_path.read_text()
    assert 'model = "echo"' in settings_content, f"Echo model not configured in settings:\n{settings_content}"

    # Verify the LLM_ECHO_RESPONSE env var override works in the agent environment
    # (This confirms the echo model's env var feature works through mng exec,
    # not just in the unit test environment.)
    custom_response = "I am a test bot and this is my canned response."
    exec_result = run_mng(
        "exec",
        agent_name,
        f'LLM_ECHO_RESPONSE="{custom_response}" llm -m echo "anything"',
    )
    assert exec_result.returncode == 0, f"llm echo failed:\nstdout: {exec_result.stdout}\nstderr: {exec_result.stderr}"
    assert extract_response(exec_result) == custom_response
