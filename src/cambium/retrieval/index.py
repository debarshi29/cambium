"""Skill retrieval index: keyword-overlap scoring over `Skill.retrieval_text()`.

CLAUDE.md §3.5: retrieval must be measured as a separate metric from task
success, because as the library grows "does the skill exist" stops being
the bottleneck and "can the agent find it" starts being one. This module is
the mechanism the `planner` prompt node's `top_k` slot drives; Sprint 3
(cambium.retrieval.recall) adds the recall@k instrumentation that measures
how well it's working, against a human-labeled correct-skill mapping, and
logs it per generation so retrieval decay as the library grows is visible.

Deliberately not embeddings/TF-IDF: this is a project about the harness
around retrieval (is it measured, does it decay, does curation help it),
not about retrieval algorithm quality. A better scorer is a drop-in swap
behind the same `RetrievalIndex.query` signature.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.schema import Task

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "and", "or", "is", "in", "on", "by", "with",
    "write", "returning", "return", "that", "this", "as", "at", "for", "if",
})


def _tokenize(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


@dataclass
class ScoredSkill:
    skill: Skill
    score: int


class RetrievalIndex:
    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def query(self, task: Task, top_k: int) -> list:
        """Rank active skills by token overlap with the task's prompt text
        against each skill's retrieval_text() (docstring + name + category —
        never source, so this measures description quality, not grepping
        the implementation). Returns up to top_k skills with score > 0,
        highest first; ties broken by skill name for determinism."""
        query_tokens = _tokenize(task.prompt)
        scored = []
        for skill in self._registry.active():
            skill_tokens = _tokenize(skill.retrieval_text())
            overlap = len(query_tokens & skill_tokens)
            if overlap > 0:
                scored.append(ScoredSkill(skill=skill, score=overlap))
        scored.sort(key=lambda s: (-s.score, s.skill.name))
        return scored[:top_k]
