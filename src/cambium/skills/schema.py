"""Skill artifact schema. See CLAUDE.md §3.1.

Skills are immutable once admitted; edits create a new version (registry
concern, not schema concern — see cambium.skills.registry).
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, replace


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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> SkillStats:
        return SkillStats(
            invocations=int(d.get("invocations", 0)),
            successes=int(d.get("successes", 0)),
            last_used_generation=d.get("last_used_generation"),
        )


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
    # Why curation archived this version ("near-duplicate", "usage decay",
    # "size cap", ...). Kept alongside `deprecated` because "archived, not
    # deleted" (CLAUDE.md §3.6) is only auditable if the reason survives too.
    deprecation_reason: str | None = None

    def key(self) -> str:
        return f"{self.name}@v{self.version}"

    def fingerprint(self) -> str:
        """Content hash of the executable body. Two persisted libraries that
        agree on every fingerprint ran exactly the same code, whatever the
        names say -- the cheap way to diff library snapshots across runs."""
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "signature": self.signature,
            "docstring": self.docstring,
            "source": self.source,
            "fn_name": self.fn_name,
            "tests": [dict(t) for t in self.tests],
            "provenance": dict(self.provenance),
            "version": self.version,
            "deprecated": self.deprecated,
            "deprecation_reason": self.deprecation_reason,
            "stats": self.stats.to_dict(),
            "fingerprint": self.fingerprint(),
        }

    @staticmethod
    def from_dict(d: dict) -> Skill:
        skill = Skill(
            name=d["name"],
            signature=d["signature"],
            docstring=d["docstring"],
            source=d["source"],
            fn_name=d["fn_name"],
            tests=tuple(d.get("tests", ())),
            provenance=dict(d.get("provenance", {})),
            version=int(d.get("version", 1)),
            deprecated=bool(d.get("deprecated", False)),
            stats=SkillStats.from_dict(d.get("stats", {})),
            deprecation_reason=d.get("deprecation_reason"),
        )
        expected = d.get("fingerprint")
        if expected is not None and expected != skill.fingerprint():
            # Refuse to load code that never went through the admission gate.
            raise ValueError(f"fingerprint mismatch for {skill.key()}: source was modified on disk")
        return skill

    def retrieval_text(self) -> str:
        """Text used by the retrieval index (§3.5). Docstring + name + category
        — never the source, so retrieval is testing description quality, not
        grepping for the implementation."""
        category = self.provenance.get("category", "")
        return f"{self.name} {category} {self.docstring}"
