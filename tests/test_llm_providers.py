"""Provider selection and the Gemini wiring (docs/adr/0014). No network:
requests.post is mocked, and conftest clears every real key."""
from unittest.mock import MagicMock, patch

import pytest

from cambium.agent.llm_client import (
    PROVIDERS,
    GroqClient,
    GroqConfigError,
    LLMClient,
    LLMConfigError,
    resolve_provider,
)
from cambium.agent.llm_generation import extract_code, llm_critic_is_general
from cambium.tasks.pack import load_task_pack


def _ok(content="def f():\n    return 1"):
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_gemini_key_alone_selects_gemini_with_gemma_4(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    client = LLMClient()
    assert client.provider == "gemini"
    assert client.model == "gemma-4-31b-it"
    assert client.max_tokens == 4096


def test_groq_key_alone_selects_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "q-key")
    client = LLMClient()
    assert client.provider == "groq"
    assert client.model == "openai/gpt-oss-20b"


def test_both_keys_prefer_groq_unless_llm_provider_says_otherwise(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "q-key")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    assert resolve_provider().name == "groq"
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert resolve_provider().name == "gemini"


def test_unknown_provider_is_a_config_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(LLMConfigError):
        LLMClient()


def test_model_env_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
    assert LLMClient().model == "gemma-4-26b-a4b-it"
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    assert LLMClient().model == "gemini-2.5-flash"
    assert LLMClient(model="explicit").model == "explicit"


def test_gemini_request_hits_the_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    client = LLMClient(retries=0)
    with patch("cambium.agent.llm_client.requests.post", return_value=_ok("hi")) as post:
        assert client.chat("sys", "usr") == "hi"
    url = post.call_args.args[0]
    assert url == PROVIDERS["gemini"].url
    assert url.startswith("https://generativelanguage.googleapis.com/v1beta/openai/")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer g-key"
    body = post.call_args.kwargs["json"]
    assert body["model"] == "gemma-4-31b-it"
    assert body["messages"][0] == {"role": "system", "content": "sys"}


def test_missing_gemini_key_names_the_right_variable():
    client = LLMClient(provider="gemini")
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        client.chat("s", "u")


def test_null_content_is_retried_then_raised(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    client = LLMClient(retries=1)
    empty = _ok()
    empty.json.return_value = {"choices": [{"message": {"content": None}}]}
    with patch("cambium.agent.llm_client.requests.post", return_value=empty) as post, \
            patch("cambium.agent.llm_client.time.sleep"):
        with pytest.raises(KeyError):
            client.chat("s", "u")
    assert post.call_count == 2


def test_bad_request_fails_fast_with_the_api_message(monkeypatch):
    """Found live: GEMINI_MODEL set to the display name "Gemma 4 31B" got a
    400 that was retried 3 times and surfaced as a bare traceback."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    client = LLMClient(model="Gemma 4 31B", retries=3)
    bad = MagicMock(status_code=400, text="")
    bad.json.return_value = [{"error": {"code": 400,
                                        "message": "unexpected model name format"}}]
    with patch("cambium.agent.llm_client.requests.post", return_value=bad) as post, \
            patch("cambium.agent.llm_client.time.sleep") as sleep:
        with pytest.raises(LLMConfigError) as exc:
            client.chat("s", "u")
    assert post.call_count == 1 and sleep.call_count == 0
    msg = str(exc.value)
    assert "unexpected model name format" in msg
    assert "'Gemma 4 31B'" in msg and "gemma-4-31b-it" in msg


def test_server_errors_are_still_retried(monkeypatch):
    import requests

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    client = LLMClient(retries=1)
    down = MagicMock(status_code=503, headers={})
    down.raise_for_status.side_effect = requests.HTTPError("503")
    with patch("cambium.agent.llm_client.requests.post", side_effect=[down, _ok("x")]) as post, \
            patch("cambium.agent.llm_client.time.sleep"):
        assert client.chat("s", "u") == "x"
    assert post.call_count == 2


def test_groq_client_name_still_works_and_stays_on_groq(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")  # even with a Gemini key present
    client = GroqClient()
    assert client.provider == "groq"
    assert GroqConfigError is LLMConfigError
    with pytest.raises(GroqConfigError, match="GROQ_API_KEY"):
        client.chat("s", "u")


def test_extract_code_takes_the_final_block_after_reasoning():
    reply = (
        "Let me think. A first draft:\n```python\ndef f(x):\n    return 0\n```\n"
        "That fails for negatives. Final answer:\n```python\ndef f(x):\n    return abs(x)\n```"
    )
    assert extract_code(reply) == "def f(x):\n    return abs(x)"


@pytest.mark.parametrize("reply,general", [
    ("GENERAL", True),
    ("OVERFIT", False),
    ("Could this be OVERFIT? No, it computes the value. GENERAL", True),
    ("It looks GENERAL at first, but the dict is keyed on the examples. OVERFIT", False),
    ("no verdict given", True),  # advisory only; the reuse check still decides
])
def test_critic_uses_the_final_verdict(reply, general):
    task = load_task_pack().by_id("fibonacci_1")

    class Stub:
        def chat(self, system, user):
            return reply

    assert llm_critic_is_general("def fib_n(n): return n", task, Stub()) is general
