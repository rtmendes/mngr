from pathlib import Path
from unittest.mock import patch

import pytest

from imbue.mngr.config.data_types import MngrContext
from imbue.mngr.errors import ProviderUnavailableError
from imbue.mngr.primitives import ProviderInstanceName
from imbue.mngr_modal.backend import ModalProviderBackend
from imbue.mngr_modal.backend import get_files_for_deploy
from imbue.mngr_modal.config import ModalMode
from imbue.mngr_modal.config import ModalProviderConfig
from imbue.modal_proxy.errors import ModalProxyError

# =============================================================================
# build_provider_instance Tests
# =============================================================================


def test_build_provider_instance_converts_modal_proxy_error_to_provider_unavailable(
    temp_mngr_ctx: MngrContext,
) -> None:
    """build_provider_instance wraps ModalProxyError as ProviderUnavailableError.

    When _get_or_create_app raises ModalProxyError (e.g. the Modal environment
    has been deleted), the error is converted to ProviderUnavailableError so
    that callers can treat the provider as temporarily unavailable rather than
    crashing the entire list operation.
    """
    config = ModalProviderConfig(
        mode=ModalMode.TESTING,
        app_name="unavailable-test-app",
        host_dir=temp_mngr_ctx.config.default_host_dir,
    )
    with patch.object(
        ModalProviderBackend,
        "_get_or_create_app",
        side_effect=ModalProxyError("Environment 'mngr-abc123' not found"),
    ):
        with pytest.raises(ProviderUnavailableError, match="Environment 'mngr-abc123' not found"):
            ModalProviderBackend.build_provider_instance(
                name=ProviderInstanceName("modal"),
                config=config,
                mngr_ctx=temp_mngr_ctx,
            )


# =============================================================================
# get_files_for_deploy Tests
# =============================================================================


def test_get_files_for_deploy_returns_empty_when_user_settings_excluded(
    temp_mngr_ctx: MngrContext, tmp_path: Path
) -> None:
    """get_files_for_deploy returns empty dict when include_user_settings is False."""
    result = get_files_for_deploy(
        mngr_ctx=temp_mngr_ctx, include_user_settings=False, include_project_settings=True, repo_root=tmp_path
    )

    assert result == {}


def test_get_files_for_deploy_returns_empty_when_no_modal_dir(temp_mngr_ctx: MngrContext, tmp_path: Path) -> None:
    """get_files_for_deploy returns empty dict when no modal provider directory exists."""
    result = get_files_for_deploy(
        mngr_ctx=temp_mngr_ctx, include_user_settings=True, include_project_settings=True, repo_root=tmp_path
    )

    assert result == {}


def test_get_files_for_deploy_excludes_ssh_key_files(temp_mngr_ctx: MngrContext, tmp_path: Path) -> None:
    """get_files_for_deploy excludes SSH key files from the modal provider directory."""
    modal_dir = temp_mngr_ctx.profile_dir / "providers" / "modal"
    modal_dir.mkdir(parents=True)
    (modal_dir / "modal_ssh_key").write_text("private-key-data")
    (modal_dir / "modal_ssh_key.pub").write_text("public-key-data")
    (modal_dir / "known_hosts").write_text("[localhost]:2222 ssh-ed25519 AAAA...")

    result = get_files_for_deploy(
        mngr_ctx=temp_mngr_ctx, include_user_settings=True, include_project_settings=True, repo_root=tmp_path
    )

    assert result == {}


def test_get_files_for_deploy_includes_non_key_files(temp_mngr_ctx: MngrContext, tmp_path: Path) -> None:
    """get_files_for_deploy includes non-key files from the modal provider directory."""
    modal_dir = temp_mngr_ctx.profile_dir / "providers" / "modal"
    modal_dir.mkdir(parents=True)
    config_file = modal_dir / "config.json"
    config_file.write_text('{"modal": "config"}')

    result = get_files_for_deploy(
        mngr_ctx=temp_mngr_ctx, include_user_settings=True, include_project_settings=True, repo_root=tmp_path
    )

    assert len(result) == 1
    matched_values = list(result.values())
    assert matched_values[0] == config_file
