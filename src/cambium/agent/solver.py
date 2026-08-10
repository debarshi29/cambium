"""The agent's solving policy.

IMPORTANT — read docs/adr/0002-agent-stand-in.md before trusting any number
this produces as evidence about LLM code generation. This project's subject
is the library machinery (admission gates, retrieval, curation, evaluation)
around an evolving tool/prompt library, not code-generation quality itself.
`BaseSolver` is a deterministic, scripted stand-in for what would ordinarily
be an LLM call: given a task, it either (a) already knows how to solve the
task's category natively (`base_capabilities`), or (b) fails. It never
"generates" anything — that is `cambium.agent.generation`'s job, and that
module is equally scripted, for the same documented reason. The interface
(`Solver.attempt`) is the seam where a real LLM-backed solver would plug in
without changing anything else in the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

from cambium.agent.base_capabilities import base_capability_source, has_base_capability
from cambium.tasks.schema import Task


@dataclass
class AttemptResult:
    solved: bool
    source: str | None
    fn_name: str
    strategy: str  # "base_capability" | "skill_reuse" | "generation" | "none"


class BaseSolver:
    """library-off: no skill registry, no retrieval. Purely base capabilities."""

    def attempt(self, task: Task) -> AttemptResult:
        if has_base_capability(task.category):
            return AttemptResult(
                solved=True,
                source=base_capability_source(task.category),
                fn_name=task.fn_name,
                strategy="base_capability",
            )
        return AttemptResult(solved=False, source=None, fn_name=task.fn_name, strategy="none")
