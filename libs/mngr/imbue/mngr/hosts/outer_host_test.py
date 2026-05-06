"""Unit tests for OuterHost and the outer-host accessors."""

from imbue.mngr.config.data_types import MngrContext
from imbue.mngr.hosts.host import Host
from imbue.mngr.hosts.outer_host import OuterHost
from imbue.mngr.hosts.outer_host import create_local_pyinfra_host
from imbue.mngr.hosts.outer_host import create_ssh_pyinfra_host_using_user_config
from imbue.mngr.interfaces.data_types import PyinfraConnector
from imbue.mngr.interfaces.host import OuterHostInterface
from imbue.mngr.primitives import HostId


def test_outer_host_satisfies_outer_host_interface(temp_mngr_ctx: MngrContext) -> None:
    """A constructed OuterHost is an instance of OuterHostInterface."""
    pyinfra_host = create_local_pyinfra_host()
    outer = OuterHost(
        id=HostId.generate(),
        connector=PyinfraConnector(pyinfra_host),
        mngr_ctx=temp_mngr_ctx,
    )
    assert isinstance(outer, OuterHostInterface)


def test_outer_host_local_is_local(temp_mngr_ctx: MngrContext) -> None:
    """An OuterHost wrapping a local pyinfra connector reports is_local=True."""
    pyinfra_host = create_local_pyinfra_host()
    outer = OuterHost(
        id=HostId.generate(),
        connector=PyinfraConnector(pyinfra_host),
        mngr_ctx=temp_mngr_ctx,
    )
    assert outer.is_local is True


def test_outer_host_local_get_ssh_connection_info_is_none(temp_mngr_ctx: MngrContext) -> None:
    """Local OuterHost has no SSH connection info."""
    pyinfra_host = create_local_pyinfra_host()
    outer = OuterHost(
        id=HostId.generate(),
        connector=PyinfraConnector(pyinfra_host),
        mngr_ctx=temp_mngr_ctx,
    )
    assert outer.get_ssh_connection_info() is None


def test_outer_host_local_executes_command(temp_mngr_ctx: MngrContext) -> None:
    """A local OuterHost can run a shell command and capture stdout."""
    pyinfra_host = create_local_pyinfra_host()
    outer = OuterHost(
        id=HostId.generate(),
        connector=PyinfraConnector(pyinfra_host),
        mngr_ctx=temp_mngr_ctx,
    )
    result = outer.execute_idempotent_command("echo hello-from-outer")
    assert result.success
    assert "hello-from-outer" in result.stdout


def test_host_is_outer_host_interface() -> None:
    """A regular Host is also an OuterHostInterface (so providers can return Host as outer)."""
    assert issubclass(Host, OuterHostInterface)


def test_outer_host_get_name_strips_at_prefix(temp_mngr_ctx: MngrContext) -> None:
    """OuterHost.get_name strips the leading '@' that pyinfra uses for local connectors."""
    pyinfra_host = create_local_pyinfra_host()
    outer = OuterHost(
        id=HostId.generate(),
        connector=PyinfraConnector(pyinfra_host),
        mngr_ctx=temp_mngr_ctx,
    )
    name = outer.get_name()
    assert not str(name).startswith("@")
    assert str(name) == "local"


def test_create_ssh_pyinfra_host_carries_user_and_port() -> None:
    """The SSH-pyinfra-host helper sets ssh_user and ssh_port on host data."""
    pyinfra_host = create_ssh_pyinfra_host_using_user_config(
        hostname="example.com",
        port=2222,
        user="alice",
    )
    assert pyinfra_host.data.get("ssh_user") == "alice"
    assert pyinfra_host.data.get("ssh_port") == 2222


def test_create_ssh_pyinfra_host_no_key_set() -> None:
    """The SSH-pyinfra-host helper does NOT set ssh_key (deferred to user's ~/.ssh)."""
    pyinfra_host = create_ssh_pyinfra_host_using_user_config(hostname="example.com")
    assert pyinfra_host.data.get("ssh_key") is None
