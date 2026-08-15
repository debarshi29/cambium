"""Sprint 3 demo: recall@k as the library grows and gains competing
vocabulary. Shows a real, unplanned collision (fibonacci_skill's docstring
beats primality_skill's on a primality query, via a shared "number" token)
plus a synthetic decoy added on top to push recall@1 down further, and how
raising k recovers it -- the mechanism the planner prompt's top_k slot
exists to control.

Run:
    python scripts/run_recall_demo.py
"""
import _pathfix  # noqa: F401

from cambium.agent.generation import CATEGORY_DOCSTRING, candidates_for
from cambium.agent.loop import build_skill_candidate
from cambium.retrieval.recall import measure_recall_at_k
from cambium.skills.admission import admit_skill
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()


def admit_all_correct_skills() -> SkillRegistry:
    registry = SkillRegistry()
    for category in CATEGORY_DOCSTRING:
        origin = next(t for t in PACK.train if t.category == category)
        source = candidates_for(category)[1].source
        candidate = build_skill_candidate(origin, source, generation=1)
        result = admit_skill(candidate, registry, PACK)
        assert result.admitted
    return registry


def make_decoy(name: str, docstring: str) -> Skill:
    return Skill(
        name=name, signature="decoy_fn(...)", docstring=docstring, source="def decoy_fn():\n    pass",
        fn_name="decoy_fn", tests=(), provenance={"task_id": "none", "generation": 0, "category": "decoy"},
    )


def report_row(registry, k, generation):
    r = measure_recall_at_k(registry, PACK, k=k, generation=generation)
    misses = ", ".join(r.misses) if r.misses else "none"
    print(f"  k={k}: {r.hits}/{r.total} = {r.recall_at_k:.0%}  (misses: {misses})")


if __name__ == "__main__":
    registry = admit_all_correct_skills()
    print("7 skills admitted, no decoys:")
    report_row(registry, 1, 1)
    report_row(registry, 2, 1)

    print("\n+ 1 decoy targeting fibonacci's own vocabulary:")
    registry.add(make_decoy("aaa_decoy_skill", CATEGORY_DOCSTRING["fibonacci"] + " fibonacci"))
    report_row(registry, 1, 2)
    report_row(registry, 3, 2)

    print("\n+ 2 more generic decoys (broad vocabulary overlap):")
    registry.add(make_decoy("aab_decoy_skill", "Convert a string value using an integer transformation."))
    registry.add(make_decoy("aac_decoy_skill", "Compute an integer result from two integer inputs."))
    report_row(registry, 1, 3)
    report_row(registry, 3, 3)
