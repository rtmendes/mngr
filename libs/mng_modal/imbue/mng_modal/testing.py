"""Test utilities for mng_modal.

Non-fixture helpers for creating test objects. Fixtures that use these
helpers live in conftest.py.
"""

from pathlib import Path

from imbue.mng.config.data_types import MngContext
from imbue.mng.primitives import ProviderInstanceName
from imbue.mng_modal.backend import STATE_VOLUME_SUFFIX
from imbue.mng_modal.config import ModalMode
from imbue.mng_modal.config import ModalProviderConfig
from imbue.mng_modal.instance import ModalProviderApp
from imbue.mng_modal.instance import ModalProviderInstance
from imbue.modal_proxy.testing import TestingModalInterface


def make_testing_modal_interface(tmp_path: Path) -> TestingModalInterface:
    """Create a TestingModalInterface rooted in a temp directory."""
    root = tmp_path / "modal_testing"
    root.mkdir(parents=True, exist_ok=True)
    return TestingModalInterface(root_dir=root)


def make_testing_provider(
    mng_ctx: MngContext,
    modal_interface: TestingModalInterface,
    app_name: str = "test-app",
    is_persistent: bool = False,
    is_snapshotted_after_create: bool = False,
    is_host_volume_created: bool = True,
) -> ModalProviderInstance:
    """Create a ModalProviderInstance backed by TestingModalInterface."""
    environment_name = f"{mng_ctx.config.prefix}test-user"

    app = modal_interface.app_lookup(app_name, create_if_missing=True, environment_name=environment_name)
    volume_name = f"{app_name}{STATE_VOLUME_SUFFIX}"
    volume = modal_interface.volume_from_name(
        volume_name,
        create_if_missing=True,
        environment_name=environment_name,
    )

    config = ModalProviderConfig(
        mode=ModalMode.TESTING,
        app_name=app_name,
        host_dir=mng_ctx.config.default_host_dir,
        default_sandbox_timeout=300,
        default_cpu=0.5,
        default_memory=0.5,
        is_persistent=is_persistent,
        is_snapshotted_after_create=is_snapshotted_after_create,
        is_host_volume_created=is_host_volume_created,
    )

    modal_app = ModalProviderApp(
        app_name=app_name,
        environment_name=environment_name,
        app=app,
        volume=volume,
        modal_interface=modal_interface,
        close_callback=lambda: None,
        get_output_callback=lambda: "",
    )

    return ModalProviderInstance(
        name=ProviderInstanceName("modal-test"),
        host_dir=mng_ctx.config.default_host_dir,
        mng_ctx=mng_ctx,
        config=config,
        modal_app=modal_app,
    )
