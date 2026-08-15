"""Sprint 4 demo: curation keeping both libraries bounded.

Run:
    python scripts/run_curation_demo.py
"""
import _pathfix  # noqa: F401

from cambium.curation.curator import run_curation
from cambium.prompts.defaults import REFLECTOR_V1, seed_default_registry
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill


def make_skill(name, docstring, invocations=0, successes=0, last_used=None):
    s = Skill(
        name=name, signature="fn(...)", docstring=docstring, source="def fn():\n    pass",
        fn_name="fn", tests=(), provenance={"task_id": "t", "generation": 1, "category": "demo"},
    )
    for i in range(invocations):
        s.stats = s.stats.record(last_used or 1, i < successes)
    return s


if __name__ == "__main__":
    skills = SkillRegistry()
    skills.add(make_skill("gcd_v1", "Compute the greatest common divisor of two integers.", 4, 4, 8))
    skills.add(make_skill("gcd_v2_dup", "Compute the greatest common divisor of two numbers.", 4, 1, 8))
    skills.add(make_skill("stale_weak", "A skill nobody uses and rarely worked.", 2, 0, 1))
    skills.add(make_skill("healthy", "A skill that works and gets used.", 5, 5, 9))

    prompts = seed_default_registry()
    prompts.add(Prompt(
        name="reflector-v2", node="reflector", template="Retry up to max_attempts=2 time(s).",
        docstring="Raised retry budget.", eval_task_ids=(),
        provenance={"parent": REFLECTOR_V1.key(), "generation": 1}, version=2,
    ))

    print("before curation:")
    print(f"  active skills: {sorted(s.name for s in skills.active())}")
    print(f"  reflector versions live: {[v.version for v in prompts.all_versions('reflector') if not v.deprecated]}")

    # dedup_similarity lowered from the 0.8 default to 0.5 for this demo:
    # "...of two integers." vs "...of two numbers." land at 0.58 Jaccard,
    # illustrative of a near-duplicate the admission gate's exact-signature
    # check wouldn't catch (see cambium.curation.curator.dedup_skills).
    report = run_curation(skills, prompts, generation=10, max_active_skills=3, dedup_similarity=0.5)

    print("\nafter curation (generation=10, max_active_skills=3):")
    print(f"  deduped: {report.skills_deduped}")
    print(f"  decayed: {report.skills_decayed}")
    print(f"  capped:  {report.skills_capped}")
    print(f"  active skills: {sorted(s.name for s in skills.active())}")
    print(f"  prompts archived: {report.prompts_archived_superseded}")
    print(f"  reflector versions live: {[v.version for v in prompts.all_versions('reflector') if not v.deprecated]}")
