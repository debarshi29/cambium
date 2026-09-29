"""Prompt admission gate. CLAUDE.md §3.4:

    A prompt variant is not admitted because one run went well.

1. Evaluated on a fixed regression subset of train tasks.
2. Demonstrated improvement: matches or beats the parent's success rate on
   that subset, no task-level regression beyond a tolerance threshold.
3. Demonstrated reuse: the improvement holds across more than one task.
4. Dedup: not a near-duplicate of an existing non-deprecated variant for
   the same node.

Condition 1's regression subset is the prompt analogue of "tests pass in
sandbox" (CLAUDE.md §3.4 note) — so this module, structurally, plays the
same role for prompts that cambium.skills.admission plays for skills.

Evaluation is node-specific — see docs/adr/0005-eval-only-scoring.md.
Planner candidates are scored on retrieval + base capability alone;
reflector/critic candidates go through the full loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from cambium.agent.loop import run_task
from cambium.eval.scoring import score_tasks
from cambium.prompts.registry import PromptRegistry
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import TaskPack

log = logging.getLogger(__name__)


@dataclass
class PromptAdmissionResult:
    admitted: bool
    reason: str  # "admitted" | "no_improvement" | "regression" | "reuse_not_demonstrated" | "duplicate"
    candidate_rate: float = 0.0
    parent_rate: float = 0.0
    gained_task_ids: tuple = ()
    regressed_task_ids: tuple = ()


def _evaluate(
    node: str,
    prompt: Prompt,
    other_nodes: dict,
    regression_task_ids: tuple,
    task_pack: TaskPack,
    base_skill_registry: SkillRegistry,
    generation: int,
) -> dict:
    """Run every regression task with `prompt` active for `node` (other
    nodes held at whatever is passed in `other_nodes`), against a private
    clone of the skill registry so trial admissions don't leak into
    production state. Returns {task_id: solved}.

    `node == "planner"` uses the eval-only scorer (retrieval + base
    capability, no generation) instead of the full loop — see module
    docstring / docs/adr/0005."""
    registry = base_skill_registry.clone()
    if node == "planner":
        return score_tasks(regression_task_ids, registry, prompt, task_pack)

    nodes = dict(other_nodes)
    nodes[node] = prompt
    out = {}
    for task_id in regression_task_ids:
        task = task_pack.by_id(task_id)
        outcome = run_task(
            task, generation, registry,
            planner=nodes["planner"], reflector=nodes["reflector"], critic=nodes["critic"],
            task_pack=task_pack,
        )
        out[task_id] = outcome.solved
    return out


def admit_prompt(candidate: Prompt, parent: Prompt, *args, **kwargs) -> PromptAdmissionResult:
    result = _admit_prompt(candidate, parent, *args, **kwargs)
    log.info(
        "prompt %s: %s vs parent %s (%.0f%% vs %.0f%%, +%d/-%d tasks)",
        "admitted" if result.admitted else f"rejected ({result.reason})",
        candidate.key(), parent.key(), 100 * result.candidate_rate, 100 * result.parent_rate,
        len(result.gained_task_ids), len(result.regressed_task_ids),
    )
    return result


def _admit_prompt(
    candidate: Prompt,
    parent: Prompt,
    other_nodes: dict,
    regression_task_ids: tuple,
    task_pack: TaskPack,
    prompt_registry: PromptRegistry,
    base_skill_registry: SkillRegistry,
    generation: int,
    regression_tolerance: int = 0,
    min_gained_tasks: int = 2,
) -> PromptAdmissionResult:
    if candidate.node != parent.node:
        raise ValueError("candidate and parent must target the same node")

    # Condition 4: dedup — same params as an existing non-deprecated variant.
    for existing in prompt_registry.all_versions(candidate.node):
        if not existing.deprecated and existing.params() == candidate.params():
            return PromptAdmissionResult(False, "duplicate")

    candidate_results = _evaluate(
        candidate.node, candidate, other_nodes, regression_task_ids,
        task_pack, base_skill_registry, generation,
    )
    parent_results = _evaluate(
        parent.node, parent, other_nodes, regression_task_ids,
        task_pack, base_skill_registry, generation,
    )

    candidate_solved = {t for t, ok in candidate_results.items() if ok}
    parent_solved = {t for t, ok in parent_results.items() if ok}
    gained = tuple(sorted(candidate_solved - parent_solved))
    regressed = tuple(sorted(parent_solved - candidate_solved))

    n = len(regression_task_ids)
    candidate_rate = len(candidate_solved) / n if n else 0.0
    parent_rate = len(parent_solved) / n if n else 0.0

    # Condition 2: matches or beats parent, no regression beyond tolerance.
    if len(regressed) > regression_tolerance:
        return PromptAdmissionResult(False, "regression", candidate_rate, parent_rate, gained, regressed)
    if candidate_rate < parent_rate:
        return PromptAdmissionResult(False, "no_improvement", candidate_rate, parent_rate, gained, regressed)

    # Condition 3: demonstrated reuse — a real gain, and not tuned to one task.
    if len(gained) == 0:
        return PromptAdmissionResult(False, "no_improvement", candidate_rate, parent_rate, gained, regressed)
    if len(gained) < min_gained_tasks:
        return PromptAdmissionResult(False, "reuse_not_demonstrated", candidate_rate, parent_rate, gained, regressed)

    prompt_registry.add(candidate)
    return PromptAdmissionResult(True, "admitted", candidate_rate, parent_rate, gained, regressed)
