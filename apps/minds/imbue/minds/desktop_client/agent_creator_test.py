"""Unit tests for agent_creator.

IMBUE_CLOUD-mode lease/rename/env-injection no longer happens in this
module: it runs inside ``ImbueCloudProvider.create_host``, reached
through the standard ``mngr create`` invocation. The plugin's own test
suite (``libs/mngr_imbue_cloud``) covers the lease + adopt path; this
file covers minds' command-building and helpers.
"""

from datetime import datetime
from datetime import timezone

from imbue.minds.desktop_client.agent_creator import _build_latchkey_gateway_url
from imbue.minds.desktop_client.agent_creator import _build_mngr_create_command
from imbue.minds.desktop_client.agent_creator import _is_git_worktree
from imbue.minds.desktop_client.agent_creator import _is_local_path
from imbue.minds.desktop_client.agent_creator import _make_host_name
from imbue.minds.desktop_client.agent_creator import _redact_url_credentials
from imbue.minds.desktop_client.agent_creator import _redact_url_credentials_in_text
from imbue.minds.desktop_client.agent_creator import extract_repo_name
from imbue.minds.desktop_client.latchkey.store import LatchkeyGatewayInfo
from imbue.minds.primitives import AgentName
from imbue.minds.primitives import LaunchMode
from imbue.mngr.primitives import AgentId


def test_extract_repo_name_strips_dot_git_and_trailing_slash() -> None:
    assert extract_repo_name("https://github.com/user/repo.git") == "repo"
    assert extract_repo_name("https://github.com/user/repo/") == "repo"
    assert extract_repo_name("https://github.com/user/Some-Repo_Name") == "Some-Repo_Name"


def test_extract_repo_name_falls_back_to_workspace() -> None:
    assert extract_repo_name("/") == "workspace"
    assert extract_repo_name("///") == "workspace"


def test_is_local_path_recognises_relative_and_absolute_paths() -> None:
    assert _is_local_path("/tmp/foo")
    assert _is_local_path("./foo")
    assert _is_local_path("../foo")
    assert _is_local_path("~/foo")
    assert not _is_local_path("https://example.com/foo")
    assert not _is_local_path("git@github.com:user/repo.git")


def test_redact_url_credentials_strips_userinfo_for_schemed_urls() -> None:
    assert _redact_url_credentials("https://x-access-token:tok@github.com/user/repo") == "https://github.com/user/repo"
    assert _redact_url_credentials("https://github.com/user/repo") == "https://github.com/user/repo"


def test_redact_url_credentials_in_text_strips_embedded_userinfo() -> None:
    msg = "fatal: unable to access 'https://user:secret@github.com/x/y': bad"
    assert _redact_url_credentials_in_text(msg) == "fatal: unable to access 'https://github.com/x/y': bad"


def test_make_host_name_appends_host_suffix() -> None:
    assert _make_host_name(AgentName("alpha")) == "alpha-host"


def _make_gateway_info(host: str = "127.0.0.1", port: int = 12345) -> LatchkeyGatewayInfo:
    return LatchkeyGatewayInfo(
        host=host,
        port=port,
        agent_id=AgentId.generate(),
        pid=1234,
        started_at=datetime.now(timezone.utc),
    )


def test_build_latchkey_gateway_url_uses_dynamic_host_for_dev() -> None:
    info = _make_gateway_info(host="127.0.0.1", port=12345)
    assert _build_latchkey_gateway_url(LaunchMode.DEV, info) == "http://127.0.0.1:12345"


def test_build_latchkey_gateway_url_uses_constant_loopback_for_remote() -> None:
    info = _make_gateway_info(host="ignored", port=99)
    for mode in (LaunchMode.LOCAL, LaunchMode.LIMA, LaunchMode.CLOUD, LaunchMode.IMBUE_CLOUD):
        url = _build_latchkey_gateway_url(mode, info)
        assert url.startswith("http://127.0.0.1:")
        assert url != "http://127.0.0.1:99"


def test_build_mngr_create_command_uses_main_template_and_omits_message_arg() -> None:
    agent_id = AgentId.generate()
    command, api_key = _build_mngr_create_command(
        launch_mode=LaunchMode.LOCAL,
        agent_name=AgentName("hello"),
        agent_id=agent_id,
    )
    assert "--template" in command
    assert "main" in command
    # The /welcome message now lives in forever-claude-template's
    # [create_templates.main] section, so the explicit --message arg is gone.
    assert "--message" not in command
    assert api_key
    assert f"--id\n{agent_id}".replace("\n", " ") in " ".join(command)


def test_build_mngr_create_command_imbue_cloud_targets_account_provider() -> None:
    agent_id = AgentId.generate()
    command, api_key = _build_mngr_create_command(
        launch_mode=LaunchMode.IMBUE_CLOUD,
        agent_name=AgentName("hello"),
        agent_id=agent_id,
        imbue_cloud_account="alice@imbue.com",
        imbue_cloud_repo_url="https://github.com/imbue-ai/forever-claude-template",
        imbue_cloud_branch_or_tag="v1.2.3",
        imbue_cloud_anthropic_api_key="sk-test",
        imbue_cloud_anthropic_base_url="https://litellm.example.com",
    )
    joined = " ".join(command)
    # Address points at the imbue_cloud_<slug> provider so mngr routes
    # create_host to ImbueCloudProvider.
    assert "@hello-host.imbue_cloud_alice-imbue-com" in joined
    # IMBUE_CLOUD does not pass --id (the lease determines the canonical id),
    # nor --reuse / --update (each lease is one-shot).
    assert "--id" not in command
    assert "--reuse" not in command
    assert "--update" not in command
    # Lease attributes flow through --build-arg.
    assert "-b" in command
    assert "repo_url=https://github.com/imbue-ai/forever-claude-template" in command
    assert "repo_branch_or_tag=v1.2.3" in command
    # ANTHROPIC_API_KEY / BASE_URL flow via --pass-host-env (the values
    # land in the subprocess env, not the command line, so the LiteLLM
    # key isn't visible in `ps` or in mngr's logs).
    assert "ANTHROPIC_API_KEY=sk-test" not in command
    assert "ANTHROPIC_BASE_URL=https://litellm.example.com" not in command
    assert "--pass-host-env" in command
    assert "ANTHROPIC_API_KEY" in command
    assert "ANTHROPIC_BASE_URL" in command
    # IMBUE_CLOUD does not run a local template; the pool host has its own.
    assert "--template" not in command
    assert api_key


def test_is_git_worktree_returns_false_for_nonexistent_path(tmp_path) -> None:
    assert not _is_git_worktree(tmp_path / "no-such-dir")
