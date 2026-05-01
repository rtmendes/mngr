import pytest

from imbue.mngr.primitives import DockerBuilder
from imbue.mngr.providers.docker.config import DockerProviderConfig


@pytest.mark.parametrize(
    "env_value",
    ["1", "true", "yes", "TRUE", "Yes", "True"],
)
def test_builder_defaults_to_depot_when_mngr_use_depot_truthy(env_value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """MNGR_USE_DEPOT recognises the same truthy values as parse_bool_env."""
    monkeypatch.setenv("MNGR_USE_DEPOT", env_value)
    assert DockerProviderConfig().builder is DockerBuilder.DEPOT


@pytest.mark.parametrize(
    "env_value",
    ["0", "false", "no", "", "anything-else"],
)
def test_builder_defaults_to_docker_when_mngr_use_depot_falsy(env_value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Any non-truthy MNGR_USE_DEPOT value (including empty / unrecognised) selects the docker builder."""
    monkeypatch.setenv("MNGR_USE_DEPOT", env_value)
    assert DockerProviderConfig().builder is DockerBuilder.DOCKER


def test_builder_defaults_to_docker_when_mngr_use_depot_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With MNGR_USE_DEPOT unset, the default builder is docker."""
    monkeypatch.delenv("MNGR_USE_DEPOT", raising=False)
    assert DockerProviderConfig().builder is DockerBuilder.DOCKER


def test_explicit_builder_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit `builder` argument wins over the MNGR_USE_DEPOT-driven default."""
    monkeypatch.setenv("MNGR_USE_DEPOT", "1")
    assert DockerProviderConfig(builder=DockerBuilder.DOCKER).builder is DockerBuilder.DOCKER
