import pytest

from cambium.prompts.defaults import REFLECTOR_V1, seed_default_registry
from cambium.prompts.registry import PromptRegistry
from cambium.prompts.schema import Prompt


def mutated(version=2, max_attempts=2):
    return Prompt(
        name=f"reflector-v{version}", node="reflector",
        template=f"Retry up to max_attempts={max_attempts} time(s).",
        docstring="mutation", eval_task_ids=(),
        provenance={"parent": REFLECTOR_V1.key(), "generation": 1}, version=version,
    )


def test_seeded_registry_has_exactly_one_active_prompt_per_node():
    registry = seed_default_registry()
    for node in ("planner", "reflector", "critic"):
        active = registry.active(node)
        assert active.version == 1
        assert not active.deprecated


def test_higher_version_becomes_the_active_selection():
    registry = seed_default_registry()
    registry.add(mutated(version=2))
    assert registry.active("reflector").version == 2
    # the other two nodes are untouched
    assert registry.active("planner").version == 1
    assert registry.active("critic").version == 1


def test_deprecating_the_active_version_falls_back_to_the_next_live_one():
    registry = seed_default_registry()
    registry.add(mutated(version=2))
    registry.deprecate("reflector", 2)
    assert registry.active("reflector").version == 1


def test_no_live_version_raises():
    registry = PromptRegistry()
    with pytest.raises(KeyError):
        registry.active("reflector")


def test_params_parses_slot_markers_from_template_text():
    assert REFLECTOR_V1.params() == {"max_attempts": 1}
    assert mutated(version=2, max_attempts=3).params() == {"max_attempts": 3}
