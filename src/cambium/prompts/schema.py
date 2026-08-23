"""Prompt artifact schema. CLAUDE.md §3.3 — structurally parallel to the
skill artifact (§3.1), versioned per loop node rather than globally.

The three loop nodes (`planner`, `reflector`, `critic`) are fixed by
docs/adr/0001-base-loop-choice.md. A prompt's `template` is real text meant
to read as an instruction to an LLM-backed node — but because this session's
agent is the scripted stand-in from docs/adr/0002-agent-stand-in.md, each
template also embeds machine-readable `slot=value` markers that
`Prompt.params()` parses out and the loop actually obeys. This keeps the
mutation honest: editing the template text is what changes behavior, not a
side-channel config object the template merely describes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

_SLOT_RE = re.compile(r"\b(\w+)=(\d+)\b")


@dataclass
class PromptStats:
    invocations: int = 0
    wins_vs_parent: int = 0
    losses_vs_parent: int = 0
    last_used_generation: int | None = None

    def record(self, generation: int, won: bool | None) -> PromptStats:
        return replace(
            self,
            invocations=self.invocations + 1,
            wins_vs_parent=self.wins_vs_parent + (1 if won else 0),
            losses_vs_parent=self.losses_vs_parent + (1 if won is False else 0),
            last_used_generation=generation,
        )


@dataclass
class Prompt:
    name: str
    node: str  # "planner" | "reflector" | "critic"
    template: str
    docstring: str
    eval_task_ids: tuple  # tasks used to measure this variant against its parent
    provenance: dict  # {"parent": "<name>@v<version>" | None, "generation": int}
    version: int = 1
    deprecated: bool = False
    stats: PromptStats = field(default_factory=PromptStats)

    def key(self) -> str:
        return f"{self.node}:{self.name}@v{self.version}"

    def params(self) -> dict:
        """Parse `slot=value` markers out of the template. This is the
        template's actual effect on loop behavior, not documentation."""
        return {k: int(v) for k, v in _SLOT_RE.findall(self.template)}

    def retrieval_text(self) -> str:
        return f"{self.node} {self.name} {self.docstring}"
