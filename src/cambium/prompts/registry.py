"""Prompt registry: versioned per node (CLAUDE.md §3.3), exactly one active
version per node at a time — no per-task retrieval the way skills get
retrieved (§3.5's recall@k treatment doesn't apply to prompts).
"""
from __future__ import annotations

import copy

from cambium.prompts.schema import Prompt


class PromptRegistry:
    def __init__(self):
        self._by_node: dict[str, list[Prompt]] = {}

    def add(self, prompt: Prompt) -> None:
        versions = self._by_node.setdefault(prompt.node, [])
        if any(v.version == prompt.version for v in versions):
            raise ValueError(f"version collision: {prompt.key()}")
        versions.append(prompt)

    def active(self, node: str) -> Prompt:
        """The current-best admitted prompt for this node. Unlike skills,
        every node must always have exactly one active version — the loop
        cannot run without a planner/reflector/critic prompt."""
        live = [v for v in self._by_node.get(node, []) if not v.deprecated]
        if not live:
            raise KeyError(f"no active prompt for node {node!r}")
        return max(live, key=lambda p: p.version)

    def all_versions(self, node: str) -> list[Prompt]:
        return list(self._by_node.get(node, []))

    def deprecate(self, node: str, version: int, reason: str = "") -> None:
        for v in self._by_node.get(node, []):
            if v.version == version:
                v.deprecated = True
                v.deprecation_reason = reason or None
                return
        raise KeyError(f"{node}@v{version} not found")

    def record_use(self, node: str, generation: int, won: bool | None) -> None:
        prompt = self.active(node)
        prompt.stats = prompt.stats.record(generation, won)

    def nodes(self) -> list[str]:
        return sorted(self._by_node)

    def to_dict(self) -> dict:
        return {
            "prompts": [
                p.to_dict()
                for node in self.nodes()
                for p in sorted(self._by_node[node], key=lambda p: p.version)
            ]
        }

    @staticmethod
    def from_dict(d: dict) -> PromptRegistry:
        registry = PromptRegistry()
        for raw in d.get("prompts", []):
            registry.add(Prompt.from_dict(raw))
        return registry

    def clone(self) -> PromptRegistry:
        """Deep copy, used for per-generation snapshots in the eval harness
        (Sprint 5) — same reasoning as SkillRegistry.clone()."""
        return copy.deepcopy(self)
