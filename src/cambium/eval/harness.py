"""Eval harness: the three curves + the tools-vs-prompts attribution
ablation, CLAUDE.md §4.

Held-out tasks are scored with cambium.eval.scoring.score_tasks (retrieval
+ base capability only — see docs/adr/0005) at every checkpoint, never with
the full generation loop, so the curves measure what the *library* (as it
stands at that point) can do, not what the scripted generator can do fresh
every time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cambium.agent.generation import has_generation_bank
from cambium.agent.loop import run_task
from cambium.curation.curator import run_curation
from cambium.eval.scoring import score_tasks
from cambium.prompts.admission import admit_prompt
from cambium.prompts.defaults import seed_default_registry
from cambium.prompts.registry import PromptRegistry
from cambium.prompts.schema import Prompt
from cambium.retrieval.recall import measure_recall_at_k
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import TaskPack

def reflector_regression_subset(task_pack: TaskPack) -> tuple:
    """One representative train task per generation-bank category -- the
    regression subset for reflector/critic mutations (evaluated through the
    full loop). Derived from the pack rather than hardcoded, so growing the
    pack (docs/adr/0010) grows the subset with it."""
    seen, out = set(), []
    for task in task_pack.train:
        if has_generation_bank(task.category) and task.category not in seen:
            seen.add(task.category)
            out.append(task.id)
    return tuple(out)


# Scheduled scripted mutation proposals -- stand-ins for "the LLM looked at
# the failures and proposed a fix." docs/adr/0002 applies here too: this is
# not a real proposer, it's two fixed, honest experiments run at fixed
# generation boundaries so the same schedule is directly comparable across
# the library-on run and every ablation arm.
MUTATION_SCHEDULE = {
    # () = resolved at call time: reflector -> reflector_regression_subset,
    # planner -> all train tasks (see below).
    2: ("reflector", 2, ()),
    # planner regression subset (3rd tuple element) is overridden to "all
    # train tasks" below at call time: the retrieval collision this
    # mutation fixes (docs/adr/0005) only shows up once primality_skill and
    # fibonacci_skill both exist, so it needs the full train set, not just
    # one task per category, to be visible.
    3: ("planner", 2, ()),
}


def _mutation_template(node: str, value: int) -> str:
    if node == "reflector":
        return f"Retry with a new generation candidate up to max_attempts={value} time(s)."
    if node == "planner":
        return f"Retrieve the top_k={value} highest-scoring skills before attempting."
    raise ValueError(node)


@dataclass
class GenerationRecord:
    generation: int
    train_solved: int
    train_total: int
    heldout_solved: int
    heldout_total: int
    num_active_skills: int
    recall_at_1: float
    recall_at_k: float
    k: int
    skill_registry: SkillRegistry  # snapshot (cloned)
    prompt_registry: PromptRegistry  # snapshot (cloned)


@dataclass
class EvolutionConfig:
    generations: int = 4
    evolve_skills: bool = True
    evolve_prompts: bool = True
    curation_every: int = 2
    mutation_schedule: dict = field(default_factory=lambda: dict(MUTATION_SCHEDULE))
    planner_regression_task_ids: tuple = ()  # () means "all train tasks"


@dataclass
class EvolutionResult:
    label: str
    records: list  # list[GenerationRecord]
    admission_log: list  # list[(label, AdmissionResult | PromptAdmissionResult)]


def run_evolution(task_pack: TaskPack, config: EvolutionConfig, label: str = "run") -> EvolutionResult:
    skill_registry = SkillRegistry()
    prompt_registry = seed_default_registry()
    admission_log = []
    records = []
    planner_regression = config.planner_regression_task_ids or tuple(t.id for t in task_pack.train)

    for gen in range(1, config.generations + 1):
        if config.evolve_prompts and gen in config.mutation_schedule:
            node, value, regression_ids = config.mutation_schedule[gen]
            if node == "planner":
                regression_ids = planner_regression
            elif not regression_ids:
                regression_ids = reflector_regression_subset(task_pack)
            parent = prompt_registry.active(node)
            other_nodes = {n: prompt_registry.active(n) for n in ("planner", "reflector", "critic") if n != node}
            candidate = Prompt(
                name=f"{node}-mutation-gen{gen}", node=node,
                template=_mutation_template(node, value),
                docstring=f"Scripted mutation proposal at generation {gen}.",
                eval_task_ids=regression_ids,
                provenance={"parent": parent.key(), "generation": gen},
                version=parent.version + 1,
            )
            result = admit_prompt(
                candidate, parent, other_nodes, regression_ids, task_pack,
                prompt_registry, skill_registry, gen,
            )
            admission_log.append((f"prompt:{node}:gen{gen}", result))

        planner = prompt_registry.active("planner")
        reflector = prompt_registry.active("reflector")
        critic = prompt_registry.active("critic")

        train_solved = 0
        for task in task_pack.train:
            outcome = run_task(
                task, gen, skill_registry, planner, reflector, critic, task_pack,
                persist_skills=config.evolve_skills,
            )
            train_solved += int(outcome.solved)
            for admission in outcome.admission_attempts:
                admission_log.append((f"skill:{task.id}:gen{gen}", admission))

        if gen % config.curation_every == 0:
            run_curation(skill_registry, prompt_registry, gen)

        planner_now = prompt_registry.active("planner")
        heldout_ids = tuple(t.id for t in task_pack.heldout)
        heldout_scores = score_tasks(heldout_ids, skill_registry, planner_now, task_pack)
        heldout_solved = sum(heldout_scores.values())

        top_k = planner_now.params().get("top_k", 1)
        recall_1 = measure_recall_at_k(skill_registry, task_pack, k=1, generation=gen).recall_at_k
        recall_k = measure_recall_at_k(skill_registry, task_pack, k=top_k, generation=gen).recall_at_k

        records.append(GenerationRecord(
            generation=gen,
            train_solved=train_solved, train_total=len(task_pack.train),
            heldout_solved=heldout_solved, heldout_total=len(heldout_ids),
            num_active_skills=len(skill_registry),
            recall_at_1=recall_1, recall_at_k=recall_k, k=top_k,
            skill_registry=skill_registry.clone(), prompt_registry=prompt_registry.clone(),
        ))

    return EvolutionResult(label=label, records=records, admission_log=admission_log)


def score_frozen_snapshot(record: GenerationRecord, task_pack: TaskPack) -> dict:
    """CLAUDE.md §4 curve 3: freeze the library at `record`'s generation,
    score held-out with it, independent of any generation that happens
    later. Since score_tasks is a pure function of registry state, "frozen
    at N evaluated at N+k" is this same score for every k -- the point of
    the curve is comparing this flat line against curve 2's live
    trajectory from N onward, not recomputing anything per k."""
    planner = record.prompt_registry.active("planner")
    heldout_ids = tuple(t.id for t in task_pack.heldout)
    scores = score_tasks(heldout_ids, record.skill_registry, planner, task_pack)
    return {"solved": sum(scores.values()), "total": len(heldout_ids)}
