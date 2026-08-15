"""The fixed control loop: plan -> act -> verify -> reflect -> extract.

Architecture fixed by docs/adr/0001-base-loop-choice.md. Only what each
node's *active prompt* parametrizes (retrieval top_k, retry budget,
extraction threshold) and which skills exist to retrieve are allowed to
vary — the node sequence below never changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cambium.agent.base_capabilities import base_capability_source, has_base_capability
from cambium.agent.generation import CATEGORY_DOCSTRING, candidates_for, has_generation_bank
from cambium.prompts.registry import PromptRegistry
from cambium.prompts.schema import Prompt
from cambium.retrieval.index import RetrievalIndex
from cambium.sandbox.runner import run_in_sandbox
from cambium.skills.admission import AdmissionResult, admit_skill
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.pack import TaskPack
from cambium.tasks.schema import Task


@dataclass
class LoopOutcome:
    task_id: str
    solved: bool
    strategy: str  # "skill_reuse" | "base_capability" | "generation" | "none"
    skill_used: str | None = None
    admission_attempts: list = field(default_factory=list)  # list[AdmissionResult]


def build_skill_candidate(task: Task, source: str, generation: int) -> Skill:
    return Skill(
        name=f"{task.category}_skill",
        signature=f"{task.fn_name}(...)",
        docstring=CATEGORY_DOCSTRING.get(task.category, f"Solve {task.category} tasks."),
        source=source,
        fn_name=task.fn_name,
        tests=tuple(task.cases_as_dicts()),
        provenance={"task_id": task.id, "generation": generation, "category": task.category},
        version=1,
    )


def run_task(
    task: Task,
    generation: int,
    skill_registry: SkillRegistry,
    planner: Prompt,
    reflector: Prompt,
    critic: Prompt,
    task_pack: TaskPack,
    persist_skills: bool = True,
) -> LoopOutcome:
    """`persist_skills=False` is the tools-fixed arm of the Sprint 5
    tools-vs-prompts attribution ablation (CLAUDE.md §4): the critic still
    "decides" whether a candidate is novel-success-worthy, but the admission
    gate is never actually called, so nothing ever enters the registry. Task
    solving still runs the full loop (generation fallback included) — only
    persistence is disabled, isolating "does the persistent library add
    anything beyond what fresh generation gets you" from "can generation
    solve the task at all"."""
    top_k = planner.params().get("top_k", 1)
    max_attempts = reflector.params().get("max_attempts", 1)
    min_lines = critic.params().get("min_lines", 1)

    # plan + act: retrieve candidate skills, try each in ranked order
    index = RetrievalIndex(skill_registry)
    for scored in index.query(task, top_k):
        skill = scored.skill
        result = run_in_sandbox(skill.source, skill.fn_name, task.cases_as_dicts())
        skill_registry.record_use(skill.name, generation, result.ok)
        if result.ok:
            return LoopOutcome(task.id, True, "skill_reuse", skill_used=skill.name)

    # act: base capability
    if has_base_capability(task.category):
        source = base_capability_source(task.category)
        result = run_in_sandbox(source, task.fn_name, task.cases_as_dicts())
        if result.ok:
            return LoopOutcome(task.id, True, "base_capability")

    # act + reflect: generation, bounded by the reflector's retry budget
    admission_log = []
    if has_generation_bank(task.category):
        for candidate in candidates_for(task.category)[:max_attempts]:
            result = run_in_sandbox(candidate.source, task.fn_name, task.cases_as_dicts())
            if result.ok:
                # extract: critic decides whether to propose a skill candidate
                already_covered = skill_registry.has_equivalent(task.category, task.fn_name) is not None
                line_count = len([ln for ln in candidate.source.splitlines() if ln.strip()])
                if persist_skills and not already_covered and line_count >= min_lines:
                    proposed = build_skill_candidate(task, candidate.source, generation)
                    admission_log.append(admit_skill(proposed, skill_registry, task_pack))
                return LoopOutcome(task.id, True, "generation", admission_attempts=admission_log)
        return LoopOutcome(task.id, False, "none", admission_attempts=admission_log)

    return LoopOutcome(task.id, False, "none")


def run_task_with_registry(
    task: Task,
    generation: int,
    skill_registry: SkillRegistry,
    prompt_registry: PromptRegistry,
    task_pack: TaskPack,
) -> LoopOutcome:
    """Convenience wrapper: pulls each node's currently-active prompt from
    the registry. Prompt admission (cambium.prompts.admission) calls
    `run_task` directly instead, so it can substitute a not-yet-admitted
    candidate for exactly one node while the other two stay at whatever is
    currently active."""
    return run_task(
        task,
        generation,
        skill_registry,
        planner=prompt_registry.active("planner"),
        reflector=prompt_registry.active("reflector"),
        critic=prompt_registry.active("critic"),
        task_pack=task_pack,
    )
