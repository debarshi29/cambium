"""recall@k instrumentation. CLAUDE.md §3.5:

    retrieval recall@k against a human-labeled "correct skill" for a subset
    of tasks, logged per generation, so retrieval decay as the library
    grows is visible.

This is deliberately a metric *about* cambium.retrieval.index, not folded
into task success — a task can be "solved" via base capability or
generation even when retrieval completely fails to surface the right skill,
and a retrieval hit doesn't guarantee the skill's source is even correct.
Conflating the two would hide exactly the failure mode this metric exists
to catch.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cambium.retrieval.index import RetrievalIndex
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import TaskPack

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"


def load_ground_truth() -> dict:
    raw = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@dataclass
class RecallReport:
    k: int
    generation: int
    total: int  # tasks whose ground-truth skill is actually admitted right now
    hits: int
    misses: tuple  # task_ids where the correct (admitted) skill wasn't in top-k

    @property
    def recall_at_k(self) -> float:
        return self.hits / self.total if self.total else 0.0


def measure_recall_at_k(
    skill_registry: SkillRegistry,
    task_pack: TaskPack,
    k: int,
    generation: int,
    ground_truth: dict | None = None,
) -> RecallReport:
    """Only tasks whose ground-truth skill is currently an active, admitted
    skill count toward the denominator — recall measures *findability* of
    what exists, not admission coverage (that's the library-size / curation
    story in Sprint 4)."""
    ground_truth = ground_truth if ground_truth is not None else load_ground_truth()
    index = RetrievalIndex(skill_registry)
    hits = 0
    misses = []
    total = 0
    for task_id, expected_skill_name in ground_truth.items():
        if skill_registry.get_active(expected_skill_name) is None:
            continue
        total += 1
        task = task_pack.by_id(task_id)
        top = index.query(task, k)
        if any(s.skill.name == expected_skill_name for s in top):
            hits += 1
        else:
            misses.append(task_id)
    return RecallReport(k=k, generation=generation, total=total, hits=hits, misses=tuple(misses))
