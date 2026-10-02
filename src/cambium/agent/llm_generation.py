"""Live LLM-backed candidate generation — the real counterpart to
`cambium.agent.generation`'s scripted CANDIDATE_BANK.

docs/adr/0002-agent-stand-in.md named "swap a real model behind the
generation seam" as the single highest-priority gap; this module is that
swap, driving `cambium.agent.llm_client.LLMClient`. It is deliberately
kept *separate* from generation.py rather than replacing it: the scripted
bank stays the default path for the eval harness, because CLAUDE.md §6
requires determinism ("seed everything... log prompts") and a live model
call is neither deterministic nor free. `scripts/run_llm_demo.py` is the
honest, separate entry point that actually exercises this module against
the real API — see its docstring and docs/adr/0007-live-llm-integration.md.
"""
from __future__ import annotations

import re

from cambium.agent.llm_client import LLMClient
from cambium.tasks.schema import Task

_CODEGEN_SYSTEM = (
    "You are a careful Python engineer. Given a task description, write a "
    "single Python function that solves it in general (do not special-case "
    "the example values shown to you). Reply with ONLY the function "
    "definition inside a python code block -- no explanation, no extra "
    "text, no example usage, no tests, no imports of third-party packages."
)

_CRITIC_SYSTEM = (
    "You are reviewing a candidate Python function for whether it is a "
    "genuine, general solution to the stated task, versus one that "
    "hardcodes or special-cases the exact example values it was shown "
    "(e.g. a lookup table keyed on the literal example inputs). Answer "
    "with exactly one word: GENERAL or OVERFIT."
)

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)
_VERDICT_RE = re.compile(r"\b(GENERAL|OVERFIT)\b")


def extract_code(text: str) -> str:
    """Pull a function body out of an LLM reply. Uses the *last* fenced
    code block: a model that drafts before answering (Gemma 4's thinking
    mode) puts its final answer last. Falls back to the whole reply when
    there is no fence."""
    blocks = _CODE_BLOCK_RE.findall(text)
    body = blocks[-1] if blocks else text
    return body.strip()


def _example_cases_text(task: Task, n: int = 3) -> str:
    lines = []
    for case in task.cases[:n]:
        lines.append(
            f"  {task.fn_name}(*{list(case.args)}, **{case.kwargs}) == {case.expected!r}"
        )
    return "\n".join(lines)


def build_generation_prompt(
    task: Task,
    prior_source: str | None = None,
    prior_error: str | None = None,
) -> str:
    """The `reflector`-node analogue: when `prior_source`/`prior_error` are
    given (a previous attempt failed sandbox verification), the prompt
    becomes a retry-with-feedback request instead of a fresh one. Same
    node sequence as the scripted loop (docs/adr/0001) -- only the content
    of what fills the generation step is live."""
    base = (
        f"Task: {task.prompt}\n\n"
        f"The function must be named `{task.fn_name}`.\n\n"
        f"Example cases (illustration only -- do not hardcode these values, "
        f"real grading uses different inputs of the same shape):\n"
        f"{_example_cases_text(task)}"
    )
    if prior_source and prior_error:
        base += (
            f"\n\nA previous attempt failed:\n```python\n{prior_source}\n```\n"
            f"Sandbox error:\n{prior_error.strip()[-800:]}\n\n"
            f"Write a corrected version."
        )
    return base


def llm_generate(
    task: Task,
    client: LLMClient,
    prior_source: str | None = None,
    prior_error: str | None = None,
) -> str:
    """One live call: returns extracted candidate source for `task`."""
    prompt = build_generation_prompt(task, prior_source, prior_error)
    reply = client.chat(_CODEGEN_SYSTEM, prompt)
    return extract_code(reply)


def llm_critic_is_general(source: str, task: Task, client: LLMClient) -> bool:
    """Live counterpart to the scripted `min_lines` heuristic in
    `cambium.agent.generation`/`loop.py`'s critic step: asks the model
    itself whether a passing candidate looks like a generalizable solution
    or a hardcoded lookup, before bothering to propose it to the admission
    gate. This is advisory only -- `cambium.skills.admission`'s reuse check
    (CLAUDE.md §3.2 condition 4) is what actually decides admission, by
    running the candidate against a second, different task. If the LLM's
    judgment here disagrees with what the gate finds on re-run, the gate's
    verdict wins; this only gates whether a proposal is attempted."""
    prompt = f"Task: {task.prompt}\n\nCandidate solution:\n```python\n{source}\n```"
    reply = client.chat(_CRITIC_SYSTEM, prompt).upper()
    # The *last* verdict wins: a model that reasons before answering may
    # mention both words on the way ("is this OVERFIT? ... GENERAL").
    verdicts = _VERDICT_RE.findall(reply)
    return not verdicts or verdicts[-1] != "OVERFIT"
