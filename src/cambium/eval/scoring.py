"""Eval-time scoring: retrieval + base capability only, **no generation**.

This is deliberately a different (narrower) code path than
cambium.agent.loop.run_task. Two places need exactly this narrower path,
for the same underlying reason:

1. **Held-out curves.** Running the full loop (with generation + admission)
   at held-out scoring time would mean admission decisions could be made
   using held-out tasks as the reuse-check partner (docs/adr/0003 forbids
   this) and would conflate "does the library help" with "can the scripted
   generator solve this fresh every time regardless of any library" — the
   whole point of the three curves is to isolate the former.
2. **Planner prompt admission.** The planner's only job is retrieval
   (CLAUDE.md §3.5's `top_k`). Evaluating a planner mutation through the
   full loop hides retrieval failures behind the reflector's generation
   fallback — in this repo's scaled demo, generation reliably re-solves a
   task from scratch even when retrieval picks the wrong skill, so a
   planner mutation that only fixes retrieval never looks like an
   improvement on the train regression subset and can never be admitted.
   That's a real methodological trap: judging a retrieval-only prompt by a
   loop that doesn't isolate retrieval. Scoring planner candidates with
   this narrower path instead measures what the planner actually changes.
   See docs/adr/0005-eval-only-scoring.md.
"""
from __future__ import annotations

from cambium.agent.base_capabilities import base_capability_source, has_base_capability
from cambium.prompts.schema import Prompt
from cambium.retrieval.index import RetrievalIndex
from cambium.sandbox.runner import run_in_sandbox
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import TaskPack
from cambium.tasks.schema import Task


def retrieval_or_base_solved(task: Task, skill_registry: SkillRegistry, planner: Prompt) -> bool:
    top_k = planner.params().get("top_k", 1)
    index = RetrievalIndex(skill_registry)
    for scored in index.query(task, top_k):
        skill = scored.skill
        result = run_in_sandbox(skill.source, skill.fn_name, task.cases_as_dicts())
        if result.ok:
            return True
    if has_base_capability(task.category):
        source = base_capability_source(task.category)
        if run_in_sandbox(source, task.fn_name, task.cases_as_dicts()).ok:
            return True
    return False


def score_tasks(task_ids, skill_registry: SkillRegistry, planner: Prompt, task_pack: TaskPack) -> dict:
    return {
        tid: retrieval_or_base_solved(task_pack.by_id(tid), skill_registry, planner)
        for tid in task_ids
    }
