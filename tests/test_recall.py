from cambium.agent.generation import CATEGORY_DOCSTRING, candidates_for
from cambium.agent.loop import build_skill_candidate
from cambium.retrieval.recall import load_ground_truth, measure_recall_at_k
from cambium.skills.admission import admit_skill
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()


def admit_all_correct_skills() -> SkillRegistry:
    registry = SkillRegistry()
    for category in CATEGORY_DOCSTRING:
        origin = next(t for t in PACK.train if t.category == category)
        source = candidates_for(category)[1].source  # correct candidate
        candidate = build_skill_candidate(origin, source, generation=1)
        result = admit_skill(candidate, registry, PACK)
        assert result.admitted, (category, result.detail)
    return registry


def make_decoy(name: str, docstring: str, category: str = "decoy") -> Skill:
    return Skill(
        name=name, signature="decoy_fn(...)", docstring=docstring, source="def decoy_fn():\n    pass",
        fn_name="decoy_fn", tests=(),
        provenance={"task_id": "none", "generation": 0, "category": category},
    )


def test_ground_truth_loads_and_matches_skill_categories():
    gt = load_ground_truth()
    assert len(gt) == 21
    assert all(name.endswith("_skill") for name in gt.values())


def test_recall_at_1_shows_a_genuine_naturally_occurring_collision():
    """Not contrived: fibonacci_skill's docstring ("...Fibonacci number...")
    shares the token "number" with every primality task's prompt ("...a
    prime number."), tying primality_skill's own "prime" overlap. The tie
    breaks alphabetically (fibonacci_skill < primality_skill), so retrieval
    at k=1 loses all three primality tasks to an unrelated skill -- exactly
    the "can the agent find it" failure mode §3.5 exists to catch, found by
    running the real index, not manufactured for the test."""
    registry = admit_all_correct_skills()
    report = measure_recall_at_k(registry, PACK, k=1, generation=1)
    assert report.total == 21
    assert report.misses == ("primality_1", "primality_2", "primality_3")
    assert report.recall_at_k == 18 / 21

    report_k2 = measure_recall_at_k(registry, PACK, k=2, generation=1)
    assert report_k2.misses == ()
    assert report_k2.recall_at_k == 1.0


def test_recall_at_1_decays_when_a_decoy_ties_and_wins_on_name():
    """A decoy with the exact same retrieval vocabulary as the real
    fibonacci skill, ranked ahead of it purely by alphabetical tie-break,
    demonstrates the failure mode §3.5 exists to catch: retrieval can fail
    even though the correct skill is sitting right there in the library."""
    registry = admit_all_correct_skills()
    decoy = make_decoy("aaa_decoy_skill", CATEGORY_DOCSTRING["fibonacci"] + " fibonacci")
    registry.add(decoy)

    report_k1 = measure_recall_at_k(registry, PACK, k=1, generation=2)
    assert "fibonacci_1" in report_k1.misses
    assert report_k1.recall_at_k < 1.0

    # a wider planner top_k recovers it -- this is exactly the lever the
    # planner prompt's top_k slot controls.
    report_k3 = measure_recall_at_k(registry, PACK, k=3, generation=2)
    assert "fibonacci_1" not in report_k3.misses
    assert report_k3.recall_at_k > report_k1.recall_at_k


def test_recall_ignores_tasks_whose_skill_is_not_yet_admitted():
    registry = SkillRegistry()  # nothing admitted
    report = measure_recall_at_k(registry, PACK, k=1, generation=1)
    assert report.total == 0
    assert report.recall_at_k == 0.0
