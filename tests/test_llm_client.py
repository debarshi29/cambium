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

    fake_response = MagicMock()
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
