"""Tests for cambium.agent.llm_client. No real network calls -- requests.post
is mocked. The "missing key" path is real (deletes the env var), the
"happy path" is mocked."""
from unittest.mock import MagicMock, patch

import pytest

from cambium.agent.llm_client import GroqClient, GroqConfigError


def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client = GroqClient()
    with pytest.raises(GroqConfigError):
        client.chat("system", "user")


def test_chat_happy_path_returns_message_content(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = GroqClient(retries=0)

    fake_response = MagicMock(status_code=200)
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "def f(): return 1"}}]
    }
    with patch("cambium.agent.llm_client.requests.post", return_value=fake_response) as mock_post:
        result = client.chat("sys", "usr")

    assert result == "def f(): return 1"
    assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_chat_retries_then_raises(monkeypatch):
    import requests

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = GroqClient(retries=1)

    with patch(
        "cambium.agent.llm_client.requests.post",
        side_effect=requests.ConnectionError("boom"),
    ) as mock_post, patch("cambium.agent.llm_client.time.sleep"):
        with pytest.raises(requests.ConnectionError):
            client.chat("sys", "usr")

    assert mock_post.call_count == 2  # initial + 1 retry


def test_chat_honors_retry_after_header_on_429(monkeypatch):
    """A 429 shouldn't fall back to the flat 1s backoff -- it should sleep
    whatever Retry-After says (plus the small buffer), then succeed on the
    next attempt. This is the exact failure mode found live against Groq's
    free-tier token-per-minute limit."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = GroqClient(retries=1)

    rate_limited = MagicMock(status_code=429, headers={"retry-after": "2"})
    ok = MagicMock(status_code=200)
    ok.raise_for_status = MagicMock()
    ok.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with patch(
        "cambium.agent.llm_client.requests.post",
        side_effect=[rate_limited, ok],
    ) as mock_post, patch("cambium.agent.llm_client.time.sleep") as mock_sleep:
        result = client.chat("sys", "usr")

    assert result == "ok"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(2.5)  # 2 + the 0.5s buffer


def test_chat_429_exhausts_retries_raises_http_error(monkeypatch):
    import requests

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = GroqClient(retries=1)

    rate_limited = MagicMock(status_code=429, headers={})
    rate_limited.raise_for_status.side_effect = requests.HTTPError("429")

    with patch(
        "cambium.agent.llm_client.requests.post",
        return_value=rate_limited,
    ) as mock_post, patch("cambium.agent.llm_client.time.sleep") as mock_sleep:
        with pytest.raises(requests.HTTPError):
            client.chat("sys", "usr")

    assert mock_post.call_count == 2  # initial + 1 retry, then raises
    mock_sleep.assert_called_once_with(5.0)  # no Retry-After header -> fallback wait
