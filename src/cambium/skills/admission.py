"""Skill admission gate. CLAUDE.md §3.2:

    A skill is not admitted because the agent succeeded while using it.

1. Executes in sandbox without error, within timeout, no network.
2. Synthesized tests pass.
3. No existing non-deprecated skill already covers the signature (dedup).
4. Demonstrated reuse: succeeds on at least one task other than the one it
   was extracted from.

Conditions 1 and 2 collapse into one sandbox run here: the candidate's
`tests` field *is* the origin task's own cases, so passing sandbox
verification against `tests` is passing the synthesized tests. Condition 4
always resolves against a **train** task — see docs/adr/0003-scaled-demo.md
and cambium.tasks.pack.TaskPack.other_task_in_category(..., split="train").
Held-out tasks never enter an admission decision.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from cambium.sandbox.runner import run_in_sandbox
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.pack import TaskPack


@dataclass
class AdmissionResult:
    admitted: bool
    reason: str  # "admitted" | "sandbox_failed" | "duplicate" | "no_reuse_task" | "reuse_failed"
    detail: str = ""


def admit_skill(candidate: Skill, registry: SkillRegistry, task_pack: TaskPack) -> AdmissionResult:
    # Conditions 1 + 2: sandbox exec, no error, synthesized tests pass.
    origin_result = run_in_sandbox(candidate.source, candidate.fn_name, list(candidate.tests))
    if not origin_result.ok:
        return AdmissionResult(False, "sandbox_failed", origin_result.stderr)

    # Condition 3: dedup check against active (non-deprecated) skills.
    existing = registry.has_equivalent(candidate.provenance["category"], candidate.fn_name)
    if existing is not None:
        return AdmissionResult(False, "duplicate", f"already covered by {existing.key()}")

    # Condition 4: demonstrated reuse, train-only.
    origin_task = task_pack.by_id(candidate.provenance["task_id"])
    reuse_task = task_pack.other_task_in_category(origin_task, split="train")
    if reuse_task is None:
        return AdmissionResult(False, "no_reuse_task", "no other train task in this category")

    reuse_result = run_in_sandbox(candidate.source, candidate.fn_name, reuse_task.cases_as_dicts())
    if not reuse_result.ok:
        return AdmissionResult(
            False, "reuse_failed",
            f"failed on {reuse_task.id}: {reuse_result.stderr.strip().splitlines()[-1] if reuse_result.stderr else 'no output'}",
        )

    # Skills are immutable once admitted (CLAUDE.md §3.1): if this name has
    # history -- typically a version curation archived, after which the loop
    # re-solved the category -- the candidate lands as the next version
    # rather than colliding with the archived one.
    if registry.all_versions(candidate.name):
        candidate = replace(candidate, version=registry.next_version(candidate.name))
    registry.add(candidate)
    return AdmissionResult(True, "admitted", f"reuse verified on {reuse_task.id}")
