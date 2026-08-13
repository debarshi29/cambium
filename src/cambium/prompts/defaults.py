"""Hand-written baseline prompts, one per loop node. These are what the
`library-off` curve (CLAUDE.md §4) runs with — fixed, never mutated, never
admitted through the gate (they predate it, same as a hand-written skill
would).
"""
from __future__ import annotations

import copy

from cambium.prompts.registry import PromptRegistry
from cambium.prompts.schema import Prompt

PLANNER_V1 = Prompt(
    name="planner-default",
    node="planner",
    template=(
        "Before attempting a task, retrieve the top_k=1 highest-scoring "
        "skills from the active library whose docstring matches the task's "
        "category and prompt text. Attempt retrieved skills in ranked order "
        "before falling back to base capabilities or generation."
    ),
    docstring="Baseline planner: retrieve top_k=1 candidate skill before attempting.",
    eval_task_ids=(),
    provenance={"parent": None, "generation": 0},
)

REFLECTOR_V1 = Prompt(
    name="reflector-default",
    node="reflector",
    template=(
        "If an attempt fails sandbox verification, you may retry with a new "
        "generation candidate up to max_attempts=1 time(s) total before "
        "reporting the task unsolved. Do not retry more than this budget "
        "allows, even if you believe another attempt would succeed."
    ),
    docstring="Baseline reflector: a single generation attempt, no retry budget.",
    eval_task_ids=(),
    provenance={"parent": None, "generation": 0},
)

CRITIC_V1 = Prompt(
    name="critic-default",
    node="critic",
    template=(
        "After a novel success (no existing skill already covers this "
        "category), propose the winning source as a skill candidate for "
        "the admission gate only if it is at least min_lines=1 line(s) "
        "long. Do not propose candidates for categories an active skill "
        "already covers."
    ),
    docstring="Baseline critic: propose any novel successful solve as a skill candidate.",
    eval_task_ids=(),
    provenance={"parent": None, "generation": 0},
)


def seed_default_registry() -> PromptRegistry:
    """Fresh Prompt objects every call, deep-copied from the module-level
    constants. The constants themselves (PLANNER_V1 etc.) must never be
    inserted into a registry directly — Prompt/PromptStats mutate in place
    (deprecate flips a field, record_use replaces .stats), and every
    registry built from the same shared instance would silently see each
    other's mutations. (Caught by test isolation breaking across
    tests/test_curation.py cases that each called seed_default_registry()
    expecting an independent registry.)"""
    registry = PromptRegistry()
    for prompt in (PLANNER_V1, REFLECTOR_V1, CRITIC_V1):
        registry.add(copy.deepcopy(prompt))
    return registry
