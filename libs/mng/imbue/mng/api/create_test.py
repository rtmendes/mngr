from pathlib import Path

from imbue.mng.api.create import _write_host_env_vars
from imbue.mng.api.create import resolve_target_host
from imbue.mng.config.data_types import EnvVar
from imbue.mng.config.data_types import MngContext
from imbue.mng.interfaces.host import HostEnvironmentOptions
from imbue.mng.interfaces.host import OnlineHostInterface
from imbue.mng.primitives import HostName
from imbue.mng.providers.local.instance import LocalProviderInstance


def test_write_host_env_vars_writes_explicit_env_vars(
    local_provider: LocalProviderInstance,
    temp_host_dir: Path,
) -> None:
    """Test that _write_host_env_vars writes explicit env vars to the host env file."""
    host = local_provider.create_host(HostName("localhost"))

    environment = HostEnvironmentOptions(
        env_vars=(
            EnvVar(key="FOO", value="bar"),
            EnvVar(key="BAZ", value="qux"),
        ),
    )

    _write_host_env_vars(host, environment)

    host_env = host.get_env_vars()
    assert host_env["FOO"] == "bar"
    assert host_env["BAZ"] == "qux"


def test_write_host_env_vars_reads_env_files(
    local_provider: LocalProviderInstance,
    temp_host_dir: Path,
    tmp_path: Path,
) -> None:
    """Test that _write_host_env_vars reads env files and writes to the host env file."""
    host = local_provider.create_host(HostName("localhost"))

    env_file = tmp_path / "test.env"
    env_file.write_text("FILE_VAR=from_file\nANOTHER=value\n")

    environment = HostEnvironmentOptions(
        env_files=(env_file,),
    )

    _write_host_env_vars(host, environment)

    host_env = host.get_env_vars()
    assert host_env["FILE_VAR"] == "from_file"
    assert host_env["ANOTHER"] == "value"


def test_write_host_env_vars_explicit_overrides_file(
    local_provider: LocalProviderInstance,
    temp_host_dir: Path,
    tmp_path: Path,
) -> None:
    """Test that explicit env vars override values from env files."""
    host = local_provider.create_host(HostName("localhost"))

    env_file = tmp_path / "test.env"
    env_file.write_text("SHARED=from_file\nFILE_ONLY=present\n")

    environment = HostEnvironmentOptions(
        env_vars=(EnvVar(key="SHARED", value="from_explicit"),),
        env_files=(env_file,),
    )

    _write_host_env_vars(host, environment)

    host_env = host.get_env_vars()
    assert host_env["SHARED"] == "from_explicit"
    assert host_env["FILE_ONLY"] == "present"


def test_write_host_env_vars_skips_when_empty(
    local_provider: LocalProviderInstance,
    temp_host_dir: Path,
) -> None:
    """Test that _write_host_env_vars does nothing when no env vars or files are specified."""
    host = local_provider.create_host(HostName("localhost"))

    environment = HostEnvironmentOptions()

    _write_host_env_vars(host, environment)

    # The host env file should not exist (no env vars written)
    host_env = host.get_env_vars()
    assert host_env == {}


# =============================================================================
# resolve_target_host Tests
# =============================================================================


def test_resolve_target_host_with_existing_host(
    local_provider: LocalProviderInstance,
    temp_mng_ctx: MngContext,
    temp_host_dir: Path,
) -> None:
    """resolve_target_host should return the host directly when given an existing OnlineHostInterface."""
    host = local_provider.create_host(HostName("localhost"))
    assert isinstance(host, OnlineHostInterface)

    resolved = resolve_target_host(host, temp_mng_ctx)
    assert resolved.id == host.id


def test_write_host_env_vars_later_env_file_overrides_earlier(
    local_provider: LocalProviderInstance,
    temp_host_dir: Path,
    tmp_path: Path,
) -> None:
    """_write_host_env_vars should let later env files override earlier ones."""
    host = local_provider.create_host(HostName("localhost"))

    env_file_1 = tmp_path / "first.env"
    env_file_1.write_text("SHARED=from_first\nFIRST_ONLY=present\n")

    env_file_2 = tmp_path / "second.env"
    env_file_2.write_text("SHARED=from_second\nSECOND_ONLY=present\n")

    environment = HostEnvironmentOptions(
        env_files=(env_file_1, env_file_2),
    )

    _write_host_env_vars(host, environment)

    host_env = host.get_env_vars()
    assert host_env["SHARED"] == "from_second"
    assert host_env["FIRST_ONLY"] == "present"
    assert host_env["SECOND_ONLY"] == "present"
