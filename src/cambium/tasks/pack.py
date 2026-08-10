"""Loads the task pack from data/*.json and exposes train/held-out splits.

CLAUDE.md §4: ~60 tasks, 40 train / 20 held-out, in the full spec. This repo's
scaled-down demo run uses a smaller pack (see docs/adr/0003-scaled-demo.md)
with the same ratio and the same discipline: held-out tasks are never used
for skill/prompt admission decisions, only for the final eval curves.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cambium.tasks.schema import Task

DEFAULT_DATA_DIR = Path(__file__).parent / "data"


@dataclass
class TaskPack:
    tasks: tuple  # tuple[Task, ...]

    def __post_init__(self):
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task ids in pack")

    @property
    def train(self) -> list:
        return [t for t in self.tasks if t.split == "train"]

    @property
    def heldout(self) -> list:
        return [t for t in self.tasks if t.split == "heldout"]

    def by_id(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)

    def by_category(self, category: str, exclude_id: str | None = None, split: str | None = None) -> list:
        return [
            t for t in self.tasks
            if t.category == category and t.id != exclude_id and (split is None or t.split == split)
        ]

    def other_task_in_category(self, task: Task, split: str | None = None) -> Task | None:
        """Return a different task in the same category as `task`, for the
        skill/prompt admission gate's 'demonstrated reuse' condition."""
        candidates = self.by_category(task.category, exclude_id=task.id, split=split)
        return candidates[0] if candidates else None


def load_task_pack(data_dir: Path | str = DEFAULT_DATA_DIR) -> TaskPack:
    data_dir = Path(data_dir)
    tasks = []
    for path in sorted(data_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        tasks.append(Task.from_dict(raw))
    if not tasks:
        raise ValueError(f"no task files found in {data_dir}")
    return TaskPack(tasks=tuple(tasks))
