"""Tests for ``mngr forward``'s CLI option validation.

These tests stub out heavy dependencies (the FastAPI app + uvicorn loop)
by inspecting only the option-validation phase via direct calls to the
helpers. End-to-end CLI invocation is exercised by the acceptance test.
"""

import click
import pytest

from imbue.mngr_forward.cli import ForwardCliOptions
from imbue.mngr_forward.cli import _build_strategy
from imbue.mngr_forward.cli import _parse_reverse_specs
from imbue.mngr_forward.cli import _validate_options
from imbue.mngr_forward.data_types import ForwardPortStrategy
from imbue.mngr_forward.data_types import ForwardServiceStrategy
from imbue.mngr_forward.errors import ForwardManualConfigError
from imbue.mngr_forward.primitives import ReverseTunnelSpec

_BASE_FIELDS: dict[str, object] = {
    "output_format": "human",
    "quiet": False,
    "verbose": 0,
    "log_file": None,
    "log_commands": None,
    "plugin": (),
    "disable_plugin": (),
}


def _opts(**overrides: object) -> ForwardCliOptions:
    return ForwardCliOptions(**{**_BASE_FIELDS, **overrides})


def test_validation_requires_one_target() -> None:
    with pytest.raises(click.UsageError):
        _validate_options(_opts())


def test_validation_rejects_both_targets() -> None:
    with pytest.raises(click.UsageError):
        _validate_options(_opts(service="system_interface", forward_port=8080))


def test_validation_rejects_no_observe_with_service() -> None:
    with pytest.raises(ForwardManualConfigError):
        _validate_options(_opts(service="system_interface", no_observe=True))


def test_validation_accepts_no_observe_with_forward_port() -> None:
    _validate_options(_opts(forward_port=8080, no_observe=True))


def test_build_strategy_service() -> None:
    strategy = _build_strategy(_opts(service="system_interface"))
    assert isinstance(strategy, ForwardServiceStrategy)
    assert strategy.service_name == "system_interface"


def test_build_strategy_port() -> None:
    strategy = _build_strategy(_opts(forward_port=8080))
    assert isinstance(strategy, ForwardPortStrategy)
    assert strategy.remote_port == 8080


def test_parse_reverse_specs_dynamic_remote() -> None:
    specs = _parse_reverse_specs(("0:8420",))
    assert specs == (ReverseTunnelSpec(remote_port=0, local_port=8420),)


def test_parse_reverse_specs_fixed_remote() -> None:
    specs = _parse_reverse_specs(("1989:7777",))
    assert specs == (ReverseTunnelSpec(remote_port=1989, local_port=7777),)


def test_parse_reverse_specs_repeated() -> None:
    specs = _parse_reverse_specs(("8420:8420", "9090:9090"))
    assert len(specs) == 2
    assert specs[0].local_port == 8420
    assert specs[1].local_port == 9090


def test_parse_reverse_specs_rejects_missing_colon() -> None:
    with pytest.raises(click.UsageError):
        _parse_reverse_specs(("8420",))


def test_parse_reverse_specs_rejects_zero_local() -> None:
    with pytest.raises(click.UsageError):
        _parse_reverse_specs(("8420:0",))


def test_parse_reverse_specs_rejects_negative() -> None:
    with pytest.raises(click.UsageError):
        _parse_reverse_specs(("-1:8420",))


def test_parse_reverse_specs_rejects_non_integer() -> None:
    with pytest.raises(click.UsageError):
        _parse_reverse_specs(("abc:8420",))
