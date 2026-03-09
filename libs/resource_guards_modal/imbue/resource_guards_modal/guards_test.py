import imbue.resource_guards.resource_guards as resource_guards
from imbue.resource_guards_modal.guards import register_modal_guard


def test_register_modal_guard_adds_modal(
    isolated_guard_state: None,
) -> None:
    register_modal_guard()

    registered_names = [entry[0] for entry in resource_guards._registered_sdk_guards]
    assert "modal" in registered_names


def test_register_modal_guard_deduplicates_on_repeated_calls(
    isolated_guard_state: None,
) -> None:
    register_modal_guard()
    register_modal_guard()

    registered_names = [entry[0] for entry in resource_guards._registered_sdk_guards]
    assert registered_names.count("modal") == 1


def test_create_sdk_resource_guards_populates_guarded_resources_modal(
    isolated_guard_state: None,
) -> None:
    register_modal_guard()
    resource_guards.create_sdk_resource_guards()

    assert "modal" in resource_guards._guarded_resources
