"""Live smoke test: run a handful of real tasks through the real
Groq-backed agent loop (docs/adr/0002's top-priority next step, now wired
in via cambium.agent.llm_client / llm_generation / loop.run_task_llm).

Requires GROQ_API_KEY in a `.env` file at the repo root or in the
environment.

This intentionally does NOT feed the eval harness or the README's curves:
those stay scripted and reproducible on purpose (CLAUDE.md §6's
determinism constraint -- "seed everything, pin model versions, log
prompts"), and a live model call is neither deterministic nor free. This
script is the separate, honest demonstration that the ADR 0002 seam
actually works end to end against a real model. See
docs/adr/0007-live-llm-integration.md for the full writeup of what this
does and doesn't prove.

Run:
    python scripts/run_llm_demo.py
"""
import _pathfix  # noqa: F401

from cambium.agent.llm_client import GroqClient, GroqConfigError
from cambium.agent.loop import run_task_llm
from cambium.prompts.defaults import seed_default_registry
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack


def main():
    client = GroqClient()
    task_pack = load_task_pack()
    prompt_registry = seed_default_registry()
    skill_registry = SkillRegistry()

    # One train task per skill-requiring category: retrieval and the skill
    # registry both start empty, same as generation 1 of the scripted eval
    # run, so every category gets a genuine live generation attempt.
    seen_categories = set()
    demo_tasks = []
    for task in task_pack.train:
        if task.category in seen_categories:
            continue
        seen_categories.add(task.category)
        demo_tasks.append(task)

    print(f"model: {client.model}")
    print(f"tasks: {len(demo_tasks)}\n")

    for task in demo_tasks:
        try:
            outcome = run_task_llm(
                task,
                generation=1,
                skill_registry=skill_registry,
                planner=prompt_registry.active("planner"),
                reflector=prompt_registry.active("reflector"),
                critic=prompt_registry.active("critic"),
                task_pack=task_pack,
                client=client,
            )
        except GroqConfigError as exc:
            print(f"stopped: {exc}")
            return

        status = "SOLVED" if outcome.solved else "failed"
        admitted = [a for a in outcome.admission_attempts if a.admitted]
        rejected = [a for a in outcome.admission_attempts if not a.admitted]
        note = ""
        if admitted:
            note = f"  (skill admitted: {admitted[0].detail})"
        elif rejected:
            note = f"  (skill rejected: {rejected[0].reason} -- {rejected[0].detail})"
        print(f"  {task.id:26s} [{task.category:20s}] {status:7s} via {outcome.strategy}{note}")

    print(f"\nactive skills after run: {len(skill_registry.active())}")


if __name__ == "__main__":
    main()
