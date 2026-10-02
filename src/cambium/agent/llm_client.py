"""Thin chat client for OpenAI-compatible chat-completions APIs.

This is the real seam docs/adr/0002-agent-stand-in.md flagged as the
top-priority next step: a live model sits behind
`cambium.agent.llm_generation`, reachable through this client. Kept
deliberately dumb (no framework, no streaming): the point is to prove
the ADR 0002 seam works end to end, not to build an LLM SDK.

Two providers, same wire format (docs/adr/0014):

  provider  key env var       default model         endpoint
  groq      GROQ_API_KEY      openai/gpt-oss-20b    api.groq.com/openai/v1
  gemini    GEMINI_API_KEY    gemma-4-31b-it        generativelanguage.googleapis.com/v1beta/openai

The provider is `LLM_PROVIDER` if set; otherwise whichever key is present
(Groq first, for backward compatibility). The model is `LLM_MODEL`, else
the provider's own variable (`GROQ_MODEL` / `GEMINI_MODEL`), else the
default above.

The one piece of real retry logic it does need is 429 backoff. Free tiers
on both providers rate-limit a handful of back-to-back calls reliably, not
occasionally (verified live against Groq). A 429 that carries a
`Retry-After` header is retried after exactly that long; one without it
falls back to a fixed wait.

Keys come from the environment or a `.env` file at the repo root (loaded
via python-dotenv on import). `.env` is gitignored; never commit one.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_RATE_LIMIT_WAIT = 5.0  # fallback if a 429 arrives with no Retry-After


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    key_env: str
    model_env: str
    default_model: str
    # Thinking models (Gemma 4) spend output tokens on reasoning before the
    # answer; 800 was enough for gpt-oss-20b's code-only replies, not for
    # a model that thinks first.
    default_max_tokens: int
    signup_url: str


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        name="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        key_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        default_model="openai/gpt-oss-20b",
        default_max_tokens=800,
        signup_url="https://console.groq.com",
    ),
    "gemini": Provider(
        name="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        default_model="gemma-4-31b-it",
        default_max_tokens=4096,
        signup_url="https://aistudio.google.com/apikey",
    ),
}


class LLMConfigError(RuntimeError):
    """Raised when no usable provider/key is configured, or the provider
    rejects the request itself (bad model id, bad key) -- distinct from a
    transient failure so callers (e.g. `cambium llm-demo`) can print a
    clear setup message instead of a stack trace."""


# Backward-compatible name: this was GroqConfigError when Groq was the only provider.
GroqConfigError = LLMConfigError


def resolve_provider(name: str | None = None) -> Provider:
    """Explicit name, else LLM_PROVIDER, else the first provider whose key
    is set (Groq, then Gemini), else Groq (so the error names a key)."""
    choice = (name or os.environ.get("LLM_PROVIDER", "")).strip().lower()
    if choice:
        if choice not in PROVIDERS:
            raise LLMConfigError(
                f"unknown LLM provider {choice!r}; expected one of {', '.join(PROVIDERS)}"
            )
        return PROVIDERS[choice]
    for provider in PROVIDERS.values():
        if os.environ.get(provider.key_env):
            return provider
    return PROVIDERS["groq"]


def _default_model(provider: Provider) -> str:
    return (
        os.environ.get("LLM_MODEL")
        or os.environ.get(provider.model_env)
        or provider.default_model
    )


@dataclass
class LLMClient:
    """`.chat(system, user) -> str` against the resolved provider."""

    provider: str | None = None
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 0  # 0 = the provider's default
    timeout: float = 60.0
    retries: int = 3
    _provider: Provider = field(init=False, repr=False)

    def __post_init__(self):
        self._provider = resolve_provider(self.provider)
        self.provider = self._provider.name
        self.model = self.model or _default_model(self._provider)
        self.max_tokens = self.max_tokens or self._provider.default_max_tokens
        self._api_key = os.environ.get(self._provider.key_env)

    def chat(self, system: str, user: str) -> str:
        """One request/response round trip. Raises LLMConfigError if the
        provider's key isn't configured, or requests.HTTPError/Timeout on
        request failure after retries."""
        if not self._api_key:
            p = self._provider
            raise LLMConfigError(
                f"{p.key_env} not set (provider: {p.name}). Put it in a .env file "
                f"at the repo root (see .env.example) or export it. Get a key at "
                f"{p.signup_url}."
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
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.post(
                    self._provider.url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 429 and attempt < self.retries:
                    time.sleep(self._rate_limit_wait(resp))
                    continue
                if 400 <= resp.status_code < 500 and resp.status_code not in (408, 429):
                    # The request itself is wrong (unknown model id, bad key,
                    # malformed body): retrying can't help, and the API's own
                    # message is what the user needs to see.
                    raise LLMConfigError(self._client_error_message(resp))
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise KeyError("message content missing or not text")
                return content
            except (requests.RequestException, KeyError, IndexError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(1.0)
        if last_exc is None:  # only reachable with retries < 0
            raise ValueError(f"LLMClient.retries must be >= 0, got {self.retries}")
        raise last_exc

    def _client_error_message(self, resp: requests.Response) -> str:
        detail = ""
        try:
            body = resp.json()
            err = body[0] if isinstance(body, list) and body else body
            if isinstance(err, dict):
                inner = err.get("error", err)
                detail = inner.get("message", "") if isinstance(inner, dict) else str(inner)
        except ValueError:
            detail = (resp.text or "")[:500]
        msg = f"{self.provider} rejected the request ({resp.status_code}) for model {self.model!r}"
        if detail:
            msg += f": {detail.strip()}"
        if resp.status_code in (400, 404):
            msg += (f". Check the model id; the default for {self.provider} is "
                    f"{self._provider.default_model!r} (set via --model, LLM_MODEL or "
                    f"{self._provider.model_env}).")
        return msg

    @staticmethod
    def _rate_limit_wait(resp: requests.Response) -> float:
        """Seconds to sleep before retrying a 429, from the response's own
        Retry-After header (small buffer added), falling back to a fixed
        wait if the header is absent or unparseable."""
        raw = resp.headers.get("retry-after")
        if raw is not None:
            try:
                return float(raw) + 0.5
            except ValueError:
                pass
        return _DEFAULT_RATE_LIMIT_WAIT


@dataclass
class GroqClient(LLMClient):
    """Backward-compatible name. Pinned to Groq unless a provider is
    passed explicitly, so existing code that asked for Groq keeps getting
    Groq even when a Gemini key is also configured."""

    provider: str | None = "groq"
