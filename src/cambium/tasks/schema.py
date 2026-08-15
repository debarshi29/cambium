"""Task pack schema.

A Task is programmatically checkable: solving it means writing a Python
function that satisfies a fixed list of (args, kwargs) -> expected cases.
No fuzzy grading anywhere in this project — see CLAUDE.md §4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskCase:
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    expected: Any = None

    @staticmethod
    def from_dict(d: dict) -> "TaskCase":
        return TaskCase(
            args=tuple(d.get("args", [])),
            kwargs=dict(d.get("kwargs", {})),
            expected=d.get("expected"),
        )

    def to_dict(self) -> dict:
        return {"args": list(self.args), "kwargs": self.kwargs, "expected": self.expected}


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    split: str  # "train" | "heldout"
    prompt: str
    fn_name: str
    cases: tuple  # tuple[TaskCase, ...]

    def __post_init__(self):
        if self.split not in ("train", "heldout"):
            raise ValueError(f"invalid split for task {self.id!r}: {self.split!r}")
        if not self.cases:
            raise ValueError(f"task {self.id!r} has no cases")

    @staticmethod
    def from_dict(d: dict) -> "Task":
        return Task(
            id=d["id"],
            category=d["category"],
            split=d["split"],
            prompt=d["prompt"],
            fn_name=d["fn_name"],
            cases=tuple(TaskCase.from_dict(c) for c in d["cases"]),
        )

    def cases_as_dicts(self) -> list:
        return [c.to_dict() for c in self.cases]
