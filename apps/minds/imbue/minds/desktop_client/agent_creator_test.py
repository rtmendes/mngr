"""Unit tests for agent_creator.

Most LEASED-mode tests were removed when the inline lease flow was replaced
with a delegation to ``imbue_cloud_cli.claim()`` (which subprocesses
``mngr imbue_cloud claim``). The flow is now exercised by the plugin's own
test suite plus end-to-end tests in ``test_desktop_client_e2e.py``.
"""

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
    from datetime import datetime
    from datetime import timezone

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


def test_is_git_worktree_returns_false_for_nonexistent_path(tmp_path) -> None:
    assert not _is_git_worktree(tmp_path / "no-such-dir")
