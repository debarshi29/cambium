"""Curation stress test. CLAUDE.md §5, Sprint 4's done-when: "both
libraries stay bounded across 20+ generations." docs/adr/0006 recorded
that this was never actually exercised: the main eval saturates at
generation 3, after which there is nothing left to admit, so curation
never faces growth pressure.

This module supplies the pressure with a **noisy proposer**: every
generation it takes already-admitted skills and proposes variants of
them -- the same (correct) code under a new function name, with the
docstring drifted by a few words sampled from other tasks' vocabulary.
That is a realistic failure mode for a live generator: re-deriving a
skill it already has, describing it slightly differently each time.

Every variant goes through the real admission gate (`admit_skill`). The
variants are *correct*, so they pass sandbox and reuse; their
(category, fn_name) signature is new, so the exact-signature dedup check
lets them in. Nothing about the gate is relaxed -- the gate is simply not
designed to stop this, which is the point: CLAUDE.md §3.6 makes curation
responsible for it.

Two arms, identical seeds and proposals:

- **curated**: `run_curation` every `curation_every` generations, with the
  production thresholds and a size cap;
- **uncurated**: the same admissions, no curation -- the "ungated growth"
  the thesis predicts degrades the library.

Per generation we record library size (active and total versions -- the
latter proves "archived, not deleted"), deprecations by reason, held-out
solve rate, and recall@1/@k of the human-labeled canonical skills.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field

from cambium.agent.loop import run_task
from cambium.curation.curator import (
    DEFAULT_DEDUP_SIMILARITY,
    DEFAULT_MIN_SUCCESS_RATE,
    DEFAULT_UNUSED_FOR_N_GENERATIONS,
    run_curation,
)
from cambium.eval.harness import EvolutionConfig, run_evolution
from cambium.eval.scoring import score_tasks
from cambium.prompts.registry import PromptRegistry
from cambium.retrieval.index import tokenize
from cambium.retrieval.recall import measure_recall_at_k
from cambium.skills.admission import admit_skill
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.pack import TaskPack

BOOTSTRAP_GENERATIONS = 3  # the main eval's library is complete by gen 3


@dataclass
class StressConfig:
    generations: int = 25
    variants_per_generation: int = 4
    curation: bool = True
    curation_every: int = 2
    max_active_skills: int = 24
    dedup_similarity: float = DEFAULT_DEDUP_SIMILARITY
    unused_for_n_generations: int = DEFAULT_UNUSED_FOR_N_GENERATIONS
    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE
    drift_words: int = 3
    seed: int = 0


@dataclass
class StressRecord:
    generation: int
    proposed: int
    admitted: int
    active_skills: int
    total_versions: int
    deprecated_by_reason: dict = field(default_factory=dict)
    heldout_solved: int = 0
    heldout_total: int = 0
    recall_at_1: float = 0.0
    recall_at_k: float = 0.0
    k: int = 1

    def to_dict(self) -> dict:
        return dict(vars(self))


@dataclass
class StressResult:
    config: StressConfig
    records: list  # list[StressRecord]
    skill_registry: SkillRegistry
    prompt_registry: PromptRegistry


def _vocabulary(task_pack: TaskPack) -> list[str]:
    words = set()
    for task in task_pack.tasks:
        words |= tokenize(task.prompt)
    return sorted(words)


def make_variant(base: Skill, generation: int, index: int, rng: random.Random, vocab: list[str],
                 drift_words: int) -> Skill:
    """Same behavior as `base`, new function name, drifted description."""
    new_fn = f"{base.fn_name}_v{generation}_{index}"
    source = re.sub(rf"\b{re.escape(base.fn_name)}\b", new_fn, base.source)
    drift = " ".join(rng.sample(vocab, min(drift_words, len(vocab))))
    category = base.provenance["category"]
    return Skill(
        name=f"{category}_variant_g{generation}_{index}",
        signature=f"{new_fn}(...)",
        docstring=f"{base.docstring} {drift}",
        source=source,
        fn_name=new_fn,
        tests=base.tests,
        provenance={
            "task_id": base.provenance["task_id"],
            "generation": generation,
            "category": category,
            "proposer": "noisy-variant",
            "variant_of": base.key(),
        },
    )


def _bootstrap(task_pack: TaskPack) -> tuple[SkillRegistry, PromptRegistry]:
    result = run_evolution(task_pack, EvolutionConfig(generations=BOOTSTRAP_GENERATIONS), "stress-bootstrap")
    last = result.records[-1]
    return last.skill_registry.clone(), last.prompt_registry.clone()


def run_stress(task_pack: TaskPack, config: StressConfig) -> StressResult:
    skills, prompts = _bootstrap(task_pack)
    rng = random.Random(config.seed)
    vocab = _vocabulary(task_pack)
    heldout_ids = tuple(t.id for t in task_pack.heldout)
    deprecated_by_reason: Counter = Counter()
    records = []

    first = BOOTSTRAP_GENERATIONS + 1
    for gen in range(first, first + config.generations):
        # propose: variants of currently-active skills, chosen deterministically
        pool = sorted(skills.active(), key=lambda s: s.name)
        admitted = 0
        for i in range(config.variants_per_generation):
            if not pool:
                break
            base = rng.choice(pool)
            variant = make_variant(base, gen, i, rng, vocab, config.drift_words)
            if admit_skill(variant, skills, task_pack).admitted:
                admitted += 1

        # use: the train set drives every active skill's usage stats
        planner, reflector, critic = (prompts.active(n) for n in ("planner", "reflector", "critic"))
        for task in task_pack.train:
            run_task(task, gen, skills, planner, reflector, critic, task_pack)

        if config.curation and gen % config.curation_every == 0:
            report = run_curation(
                skills, prompts, gen,
                dedup_similarity=config.dedup_similarity,
                unused_for_n_generations=config.unused_for_n_generations,
                min_success_rate=config.min_success_rate,
                max_active_skills=config.max_active_skills,
            )
            deprecated_by_reason["near-duplicate"] += len(report.skills_deduped)
            deprecated_by_reason["usage decay"] += len(report.skills_decayed)
            deprecated_by_reason["size cap"] += len(report.skills_capped)

        planner = prompts.active("planner")
        top_k = planner.params().get("top_k", 1)
        heldout = score_tasks(heldout_ids, skills, planner, task_pack)
        records.append(StressRecord(
            generation=gen,
            proposed=config.variants_per_generation,
            admitted=admitted,
            active_skills=len(skills),
            total_versions=len(skills.all_skills()),
            deprecated_by_reason=dict(deprecated_by_reason),
            heldout_solved=sum(heldout.values()),
            heldout_total=len(heldout_ids),
            recall_at_1=measure_recall_at_k(skills, task_pack, 1, gen).recall_at_k,
            recall_at_k=measure_recall_at_k(skills, task_pack, top_k, gen).recall_at_k,
            k=top_k,
        ))

    return StressResult(config, records, skills, prompts)
