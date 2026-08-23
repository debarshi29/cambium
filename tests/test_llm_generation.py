"""Tests for cambium.agent.llm_generation. Uses a fake client (no network,
no API key needed) so the LLM-backed plumbing is exercised by the regular
pytest run -- only scripts/run_llm_demo.py hits the real API."""
from cambium.agent.llm_generation import (
    build_generation_prompt,
    extract_code,
    llm_critic_is_general,
    llm_generate,
)
from cambium.tasks.pack import load_task_pack


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.reply


def _fib_task():
    pack = load_task_pack()
    return next(t for t in pack.train if t.category == "fibonacci")


def test_extract_code_from_fenced_block():
    text = "Here you go:\n```python\ndef f(x):\n    return x\n```\n"
    assert extract_code(text) == "def f(x):\n    return x"


def test_extract_code_bare_text_fallback():
    text = "def f(x):\n    return x"
    assert extract_code(text) == "def f(x):\n    return x"


def test_build_generation_prompt_includes_fn_name_and_task():
    task = _fib_task()
    prompt = build_generation_prompt(task)
    assert task.fn_name in prompt
    assert task.prompt in prompt
    assert "previous attempt" not in prompt


def test_build_generation_prompt_with_prior_error_is_a_retry():
    task = _fib_task()
    prompt = build_generation_prompt(task, prior_source="def fib_n(n): ...", prior_error="AssertionError: boom")
    assert "previous attempt failed" in prompt
    assert "boom" in prompt


def test_llm_generate_extracts_and_calls_client_once():
    task = _fib_task()
    client = FakeClient("```python\ndef fib_n(n):\n    return n\n```")
    source = llm_generate(task, client)
    assert source == "def fib_n(n):\n    return n"
    assert len(client.calls) == 1


def test_llm_critic_general_reply_accepts():
    task = _fib_task()
    client = FakeClient("GENERAL")
    assert llm_critic_is_general("def fib_n(n): return n", task, client) is True


def test_llm_critic_overfit_reply_rejects():
    task = _fib_task()
    client = FakeClient("OVERFIT")
    assert llm_critic_is_general("def fib_n(n): return {0: 1}.get(n)", task, client) is False
