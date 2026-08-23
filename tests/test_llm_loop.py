"""Tests for cambium.agent.loop.run_task_llm -- the live-model counterpart
to run_task (tests/test_loop.py). A scripted fake client stands in for
GroqClient so these run with no network and no API key, exercising the
same node sequence / admission-gate mechanics as the real path."""
from cambium.agent.loop import run_task_llm
from cambium.prompts.defaults import CRITIC_V1, PLANNER_V1, REFLECTOR_V1
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()

_CORRECT_FIB = "```python\ndef fib_n(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n```"
_BROKEN_FIB = "```python\ndef fib_n(n):\n    return 1 / 0\n```"

_RETRY_REFLECTOR = Prompt(
    name="reflector-retry-2", node="reflector",
    template="Retry with a new generation candidate up to max_attempts=2 time(s).",
    docstring="Allow one retry beyond the default.",
    eval_task_ids=(), provenance={"parent": "reflector-default@v1", "generation": 1},
    version=2,
)


class ScriptedClient:
    """Routes codegen calls through `codegen_replies` in order, and critic
    calls to a fixed verdict -- distinguished by which system prompt was
    sent (llm_generation._CRITIC_SYSTEM mentions OVERFIT, the codegen one
    doesn't)."""

    def __init__(self, codegen_replies, critic_reply="GENERAL"):
        self.codegen_replies = list(codegen_replies)
        self.critic_reply = critic_reply
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        if "OVERFIT" in system:
            return self.critic_reply
        return self.codegen_replies.pop(0)


def _run(task_id, skill_registry, client, reflector=REFLECTOR_V1, generation=1):
    task = PACK.by_id(task_id)
    return run_task_llm(
        task, generation, skill_registry, PLANNER_V1, reflector, CRITIC_V1, PACK, client,
    )


def test_llm_loop_solves_via_generation_and_admits_skill():
    registry = SkillRegistry()
    client = ScriptedClient([_CORRECT_FIB])
    outcome = _run("fibonacci_1", registry, client)
    assert outcome.solved
    assert outcome.strategy == "generation"
    assert len(outcome.admission_attempts) == 1
    assert outcome.admission_attempts[0].admitted
    assert len(registry) == 1

    # second task in the category now resolves via skill reuse, no LLM call
    second_client = ScriptedClient([])
    second = _run("fibonacci_2", registry, second_client, generation=2)
    assert second.solved
    assert second.strategy == "skill_reuse"
    assert second.skill_used == "fibonacci_skill"
    assert second_client.calls == []


def test_llm_loop_retries_with_error_feedback_after_sandbox_failure():
    registry = SkillRegistry()
    client = ScriptedClient([_BROKEN_FIB, _CORRECT_FIB])
    outcome = _run("fibonacci_1", registry, client, reflector=_RETRY_REFLECTOR)
    assert outcome.solved
    assert outcome.strategy == "generation"

    codegen_calls = [u for s, u in client.calls if "OVERFIT" not in s]
    assert len(codegen_calls) == 2
    assert "previous attempt failed" in codegen_calls[1]


def test_llm_loop_default_reflector_has_no_budget_for_a_retry():
    registry = SkillRegistry()
    client = ScriptedClient([_BROKEN_FIB, _CORRECT_FIB])
    outcome = _run("fibonacci_1", registry, client)  # default max_attempts=1
    assert not outcome.solved
    assert outcome.strategy == "none"
    assert len(registry) == 0


def test_llm_loop_critic_overfit_verdict_blocks_the_proposal():
    registry = SkillRegistry()
    client = ScriptedClient([_CORRECT_FIB], critic_reply="OVERFIT")
    outcome = _run("fibonacci_1", registry, client)
    assert outcome.solved
    assert outcome.admission_attempts == []
    assert len(registry) == 0
