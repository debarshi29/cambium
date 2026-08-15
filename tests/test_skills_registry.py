import pytest

from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill


def make_skill(name="fib_skill", version=1, category="fibonacci", deprecated=False):
    return Skill(
        name=name,
        signature="fib_n(n: int) -> int",
        docstring="Return the nth Fibonacci number.",
        source="def fib_n(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
        fn_name="fib_n",
        tests=(),
        provenance={"task_id": "fibonacci_1", "generation": 1, "category": category},
        version=version,
        deprecated=deprecated,
    )


def test_add_and_get_active():
    reg = SkillRegistry()
    reg.add(make_skill())
    assert reg.get_active("fib_skill").version == 1


def test_higher_version_becomes_active():
    reg = SkillRegistry()
    reg.add(make_skill(version=1))
    reg.add(make_skill(version=2))
    assert reg.get_active("fib_skill").version == 2


def test_deprecated_not_active():
    reg = SkillRegistry()
    reg.add(make_skill(version=1))
    reg.deprecate("fib_skill", 1)
    assert reg.get_active("fib_skill") is None
    assert reg.active() == []


def test_version_collision_rejected():
    reg = SkillRegistry()
    reg.add(make_skill(version=1))
    with pytest.raises(ValueError):
        reg.add(make_skill(version=1))


def test_has_equivalent_dedup_check():
    reg = SkillRegistry()
    reg.add(make_skill())
    dup = reg.has_equivalent(category="fibonacci", fn_name="fib_n")
    assert dup is not None
    assert reg.has_equivalent(category="primality", fn_name="is_prime") is None


def test_record_use_updates_stats():
    reg = SkillRegistry()
    reg.add(make_skill())
    reg.record_use("fib_skill", generation=1, success=True)
    reg.record_use("fib_skill", generation=2, success=False)
    stats = reg.get_active("fib_skill").stats
    assert stats.invocations == 2
    assert stats.successes == 1
    assert stats.last_used_generation == 2
    assert stats.success_rate == 0.5
