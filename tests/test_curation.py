from cambium.curation.curator import (
    archive_superseded_prompts,
    cap_skill_library,
    decay_deprecate_skills,
    dedup_prompts,
    dedup_skills,
    run_curation,
)
from cambium.prompts.defaults import REFLECTOR_V1, seed_default_registry
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill


def make_skill(name, docstring, category="cat", fn_name="fn", version=1,
                invocations=0, successes=0, last_used=None):
    s = Skill(
        name=name, signature=f"{fn_name}(...)", docstring=docstring, source="def fn():\n    pass",
        fn_name=fn_name, tests=(), provenance={"task_id": "t", "generation": 1, "category": category},
        version=version,
    )
    if invocations:
        for i in range(invocations):
            s.stats = s.stats.record(last_used or 1, i < successes)
    return s


def test_dedup_skills_merges_near_identical_docstrings_keeps_better_stats():
    registry = SkillRegistry()
    weak = make_skill("weak_skill", "Compute the greatest common divisor of two integers.",
                       invocations=4, successes=1)
    strong = make_skill("strong_skill", "Compute the greatest common divisor of two numbers.",
                         invocations=4, successes=4)
    registry.add(weak)
    registry.add(strong)

    merged = dedup_skills(registry, threshold=0.5)

    assert merged == [("strong_skill", "weak_skill")]
    assert registry.get_active("weak_skill") is None
    assert registry.get_active("strong_skill") is not None


def test_dedup_skills_leaves_unrelated_skills_alone():
    registry = SkillRegistry()
    registry.add(make_skill("fib_skill", "Compute the nth Fibonacci number."))
    registry.add(make_skill("roman_skill", "Convert an integer to a Roman numeral."))
    merged = dedup_skills(registry)
    assert merged == []
    assert len(registry) == 2


def test_decay_deprecates_stale_and_weak_skills_only():
    registry = SkillRegistry()
    stale_weak = make_skill("stale_weak", "docstring one", invocations=3, successes=0, last_used=1)
    stale_strong = make_skill("stale_strong", "docstring two", invocations=3, successes=3, last_used=1)
    fresh_weak = make_skill("fresh_weak", "docstring three", invocations=3, successes=0, last_used=9)
    registry.add(stale_weak)
    registry.add(stale_strong)
    registry.add(fresh_weak)

    deprecated = decay_deprecate_skills(registry, current_generation=10, unused_for_n_generations=5, min_success_rate=0.5)

    assert deprecated == ["stale_weak"]
    assert registry.get_active("stale_strong") is not None  # stale but strong: kept
    assert registry.get_active("fresh_weak") is not None    # weak but fresh: kept


def test_never_used_skill_decays_once_library_outlives_the_window():
    registry = SkillRegistry()
    registry.add(make_skill("never_used", "docstring"))  # invocations=0, last_used=None
    deprecated = decay_deprecate_skills(registry, current_generation=6, unused_for_n_generations=5)
    assert deprecated == ["never_used"]


def test_cap_skill_library_deprecates_lowest_value_until_under_cap():
    registry = SkillRegistry()
    for i in range(5):
        registry.add(make_skill(f"skill_{i}", f"docstring number {i} unique", invocations=4, successes=i))
    dropped = cap_skill_library(registry, max_active=3)
    assert len(dropped) == 2
    assert set(dropped) == {"skill_0", "skill_1"}  # lowest success rates
    assert len(registry) == 3


def test_cap_skill_library_noop_when_under_cap():
    registry = SkillRegistry()
    registry.add(make_skill("only_one", "docstring"))
    assert cap_skill_library(registry, max_active=10) == []


def test_deprecation_is_soft_version_history_preserved():
    registry = SkillRegistry()
    registry.add(make_skill("s", "docstring", invocations=0))
    decay_deprecate_skills(registry, current_generation=100)
    assert registry.get_active("s") is None
    assert len(registry.all_versions("s")) == 1  # archived, not deleted


def test_archive_superseded_prompts_keeps_only_the_max_version_undeprecated():
    registry = seed_default_registry()
    v2 = Prompt(
        name="reflector-v2", node="reflector", template="max_attempts=2",
        docstring="d", eval_task_ids=(), provenance={"parent": REFLECTOR_V1.key(), "generation": 1}, version=2,
    )
    registry.add(v2)
    archived = archive_superseded_prompts(registry)
    assert ("reflector", 1) in archived
    assert registry.active("reflector").version == 2
    assert [v.version for v in registry.all_versions("reflector") if not v.deprecated] == [2]


def test_dedup_prompts_merges_same_params_keeps_better_win_rate():
    registry = seed_default_registry()
    better = Prompt(
        name="reflector-a", node="reflector", template="max_attempts=2",
        docstring="a", eval_task_ids=(), provenance={"parent": REFLECTOR_V1.key(), "generation": 1}, version=2,
    )
    worse = Prompt(
        name="reflector-b", node="reflector", template="max_attempts=2",
        docstring="b", eval_task_ids=(), provenance={"parent": REFLECTOR_V1.key(), "generation": 1}, version=3,
    )
    better.stats = better.stats.record(1, True)
    better.stats = better.stats.record(2, True)
    worse.stats = worse.stats.record(1, False)
    registry.add(better)
    registry.add(worse)

    merged = dedup_prompts(registry)

    assert merged == [("reflector", 2, 3)]
    live_versions = {v.version for v in registry.all_versions("reflector") if not v.deprecated}
    assert live_versions == {1, 2}  # v1 (planner default untouched by this fn), v2 kept, v3 archived


def test_run_curation_combines_all_passes():
    skills = SkillRegistry()
    skills.add(make_skill("stale_weak", "unique docstring alpha", invocations=2, successes=0, last_used=1))
    prompts = seed_default_registry()
    v2 = Prompt(
        name="reflector-v2", node="reflector", template="max_attempts=2",
        docstring="d", eval_task_ids=(), provenance={"parent": REFLECTOR_V1.key(), "generation": 1}, version=2,
    )
    prompts.add(v2)

    report = run_curation(skills, prompts, generation=10)

    assert "stale_weak" in report.skills_decayed
    assert ("reflector", 1) in report.prompts_archived_superseded
