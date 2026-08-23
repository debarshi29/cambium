"""Skill artifact schema. See CLAUDE.md §3.1.

Skills are immutable once admitted; edits create a new version (registry
concern, not schema concern — see cambium.skills.registry).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class SkillStats:
    invocations: int = 0
    successes: int = 0
    last_used_generation: int | None = None

    def record(self, generation: int, success: bool) -> SkillStats:
        return replace(
            self,
            invocations=self.invocations + 1,
            successes=self.successes + (1 if success else 0),
            last_used_generation=generation,
        )

    @property
    def success_rate(self) -> float:
        return self.successes / self.invocations if self.invocations else 0.0


@dataclass
class Skill:
    name: str
    signature: str
    docstring: str
    source: str
    fn_name: str
    tests: tuple  # tuple[dict, ...] — synthesized TaskCase dicts, must pass in sandbox
    provenance: dict  # {"task_id": ..., "generation": ..., "category": ...}
    version: int = 1
    deprecated: bool = False
    stats: SkillStats = field(default_factory=SkillStats)

    def key(self) -> str:
        return f"{self.name}@v{self.version}"

    def retrieval_text(self) -> str:
        """Text used by the retrieval index (§3.5). Docstring + name + category
        — never the source, so retrieval is testing description quality, not
        grepping for the implementation."""
        category = self.provenance.get("category", "")
        return f"{self.name} {category} {self.docstring}"
