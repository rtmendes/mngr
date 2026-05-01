import pytest

from imbue.mngr.primitives import DockerBuilder
from imbue.mngr.providers.docker.config import DockerProviderConfig
from imbue.mngr.providers.docker.testing import _builder_for_tests


def test_builder_defaults_to_docker() -> None:
    """The config default is DOCKER -- production is opt-in to depot via settings.toml."""
    assert DockerProviderConfig().builder is DockerBuilder.DOCKER


def test_explicit_builder_is_honored() -> None:
    """`builder` is a plain config field; the constructor argument wins."""
    assert DockerProviderConfig(builder=DockerBuilder.DEPOT).builder is DockerBuilder.DEPOT


@pytest.mark.parametrize(
    "env_value, expected",
    [
        ("1", DockerBuilder.DEPOT),
        ("true", DockerBuilder.DEPOT),
        ("yes", DockerBuilder.DEPOT),
        ("TRUE", DockerBuilder.DEPOT),
        ("0", DockerBuilder.DOCKER),
        ("false", DockerBuilder.DOCKER),
        ("", DockerBuilder.DOCKER),
        ("anything-else", DockerBuilder.DOCKER),
    ],
)
def test_builder_for_tests_reads_mngr_use_depot(
    env_value: str, expected: DockerBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MNGR_USE_DEPOT env var only affects test fixtures, via _builder_for_tests."""
    monkeypatch.setenv("MNGR_USE_DEPOT", env_value)
    assert _builder_for_tests() is expected


def test_builder_for_tests_defaults_to_docker_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNGR_USE_DEPOT", raising=False)
    assert _builder_for_tests() is DockerBuilder.DOCKER
