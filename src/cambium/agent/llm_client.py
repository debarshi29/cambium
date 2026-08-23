"""Thin Groq client: OpenAI-compatible chat completions.

This is the real seam docs/adr/0002-agent-stand-in.md flagged as the
top-priority next step — a live model now sits behind
`cambium.agent.llm_generation`, reachable through this client. Kept
deliberately dumb (no framework, no streaming, one retry): the point is to
prove the ADR 0002 seam works end to end, not to build an LLM SDK.

Requires GROQ_API_KEY in the environment or a `.env` file at the repo root
(loaded via python-dotenv on import). Get a free key at
https://console.groq.com. `.env` is gitignored — never commit one.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqConfigError(RuntimeError):
    """Raised when GROQ_API_KEY isn't set — distinct from a request-time
    failure so callers (e.g. scripts/run_llm_demo.py) can print a clear
    setup message instead of a stack trace."""


@dataclass
class GroqClient:
    model: str = field(default_factory=lambda: DEFAULT_MODEL)
    temperature: float = 0.2
    max_tokens: int = 800
    timeout: float = 30.0
    retries: int = 1

    def __post_init__(self):
        self._api_key = os.environ.get("GROQ_API_KEY")

    def chat(self, system: str, user: str) -> str:
        """One request/response round trip. Raises GroqConfigError if no key
        is configured, or requests.HTTPError/Timeout on request failure
        after retries."""
        if not self._api_key:
            raise GroqConfigError(
                "GROQ_API_KEY not set. Put it in a .env file at the repo "
                "root (see .env.example) or export it before running an "
                "LLM-backed script."
            )
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_exc = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.post(
                    _API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (requests.RequestException, KeyError, IndexError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(1.0)
        raise last_exc
