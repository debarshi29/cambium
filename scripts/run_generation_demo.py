"""Sprint 2 sanity check: run one pass of the loop over every train task with
the default (library-off-equivalent) prompts, then again with a mutated
reflector that raises the retry budget, and show what admission actually
does — including the overfit rejection. This is not the eval harness
(that's Sprint 5); it's a demonstration that generation + both admission
gates work end-to-end.

Run:
    python scripts/run_generation_demo.py
"""
import _pathfix  # noqa: F401

from cambium.agent.loop import run_task
from cambium.prompts.defaults import CRITIC_V1, PLANNER_V1, REFLECTOR_V1
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack

MUTATED_REFLECTOR = Prompt(
    name="reflector-retry-2", node="reflector",
    template="Retry with a new generation candidate up to max_attempts=2 time(s).",
    docstring="Allow one retry beyond the default.",
    eval_task_ids=(), provenance={"parent": REFLECTOR_V1.key(), "generation": 1},
    version=2,
)


def run_pass(reflector, label):
    pack = load_task_pack()
    registry = SkillRegistry()
    print(f"\n--- {label} (reflector max_attempts={reflector.params().get('max_attempts')}) ---")
    solved = 0
    for i, task in enumerate(pack.train, start=1):
        outcome = run_task(task, i, registry, PLANNER_V1, reflector, CRITIC_V1, pack)
        solved += outcome.solved
        for admission in outcome.admission_attempts:
            status = "ADMITTED" if admission.admitted else f"REJECTED ({admission.reason})"
            print(f"  [{task.id}] skill candidate: {status} - {admission.detail}")
    print(f"  train solved: {solved}/{len(pack.train)}")
    print(f"  active skills: {[s.name for s in registry.active()]}")
    return registry


if __name__ == "__main__":
    run_pass(REFLECTOR_V1, "default reflector (max_attempts=1)")
    run_pass(MUTATED_REFLECTOR, "mutated reflector (max_attempts=2)")
