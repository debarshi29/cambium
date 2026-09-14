"""Skill registry: versioned storage, active/deprecated state.

Admission (cambium.skills.admission) decides whether a candidate gets in.
The registry just stores what's already been admitted and answers the
questions curation (cambium.curation) and retrieval (cambium.retrieval)
need to ask.
"""
from __future__ import annotations

import copy

from cambium.skills.schema import Skill


class SkillRegistry:
    def __init__(self):
        self._by_name: dict[str, list[Skill]] = {}

    def add(self, skill: Skill) -> None:
        versions = self._by_name.setdefault(skill.name, [])
        if any(v.version == skill.version for v in versions):
            raise ValueError(f"version collision: {skill.key()}")
        versions.append(skill)

    def active(self) -> list[Skill]:
        """One entry per name: the highest-version non-deprecated skill."""
        out = []
        for versions in self._by_name.values():
            live = [v for v in versions if not v.deprecated]
            if live:
                out.append(max(live, key=lambda s: s.version))
        return out

    def all_versions(self, name: str) -> list[Skill]:
        return list(self._by_name.get(name, []))

    def get_active(self, name: str) -> Skill | None:
        live = [v for v in self._by_name.get(name, []) if not v.deprecated]
        return max(live, key=lambda s: s.version) if live else None

    def has_equivalent(self, category: str, fn_name: str) -> Skill | None:
        """Dedup check (admission condition 3): is there already a
        non-deprecated skill covering this signature? A skill's signature
        is approximated here by (category, fn_name) — same category and
        same call contract means the same job."""
        for skill in self.active():
            if skill.provenance.get("category") == category and skill.fn_name == fn_name:
                return skill
        return None

    def deprecate(self, name: str, version: int, reason: str = "") -> None:
        for v in self._by_name.get(name, []):
            if v.version == version:
                v.deprecated = True
                v.deprecation_reason = reason or None
                return
        raise KeyError(f"{name}@v{version} not found")

    def record_use(self, name: str, generation: int, success: bool) -> None:
        skill = self.get_active(name)
        if skill is None:
            raise KeyError(name)
        skill.stats = skill.stats.record(generation, success)

    def all_skills(self) -> list[Skill]:
        """Every version of every skill, deprecated included, in stable
        (name, version) order -- the full audit history."""
        return [
            s
            for name in sorted(self._by_name)
            for s in sorted(self._by_name[name], key=lambda s: s.version)
        ]

    def to_dict(self) -> dict:
        return {"skills": [s.to_dict() for s in self.all_skills()]}

    @staticmethod
    def from_dict(d: dict) -> SkillRegistry:
        registry = SkillRegistry()
        for raw in d.get("skills", []):
            registry.add(Skill.from_dict(raw))
        return registry

    def __len__(self) -> int:
        return len(self.active())

    def clone(self) -> SkillRegistry:
        """Deep copy, used by prompt admission (§3.4) to evaluate a
        candidate on a regression subset without letting trial-run skill
        admissions leak into the registry actually driving production
        curves."""
        return copy.deepcopy(self)
