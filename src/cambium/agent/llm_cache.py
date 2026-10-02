"""Record/replay for live LLM calls.

CLAUDE.md §6: "Determinism where possible: seed everything, pin model
versions, log prompts." A live model is neither deterministic nor free,
which is why ADR 0007 kept it out of the reported curves. This module is
how a live run becomes reproducible anyway: every (system, user) prompt
and the model's reply are written to an append-only JSONL **cassette**,
keyed by a hash of everything that determines the request (model,
temperature, max_tokens, system, user). Replaying the cassette re-runs the
exact same experiment -- same candidates, same admission decisions, same
curves -- offline, with no API key, as many times as anyone wants.

Modes:
  record  -- always call the model; append every exchange (overwrites
             nothing: a repeated prompt appends a second entry, and the
             *first* recorded reply is what replay uses)
  replay  -- never call the model; a prompt not on the cassette raises
             LLMCacheMiss (a replay that silently went live would not be
             a replay)
  auto    -- replay when the prompt is on the cassette, otherwise call and
             record

The cassette doubles as the prompt log §6 asks for.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Protocol

MODES = ("record", "replay", "auto")


class ChatClient(Protocol):
    model: str

    def chat(self, system: str, user: str) -> str: ...


class LLMCacheMiss(LookupError):
    """Replay mode was asked for a prompt the cassette doesn't contain."""


def request_key(model: str, temperature: float, max_tokens: int, system: str, user: str) -> str:
    payload = json.dumps(
        {"model": model, "temperature": temperature, "max_tokens": max_tokens,
         "system": system, "user": user},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RecordReplayClient:
    """Drop-in for LLMClient (anything with `.chat(system, user)`)."""

    def __init__(self, cassette: Path | str, mode: str = "auto", inner: ChatClient | None = None,
                 model: str | None = None, temperature: float | None = None,
                 max_tokens: int | None = None):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if mode in ("record", "auto") and inner is None:
            raise ValueError(f"mode {mode!r} needs an inner client to call")
        self.cassette = Path(cassette)
        self.mode = mode
        self.inner = inner
        # Request parameters are part of the key; take them from the inner
        # client when there is one so record and replay agree.
        self.model: str = model or str(getattr(inner, "model", "unknown"))
        self.temperature = temperature if temperature is not None else getattr(inner, "temperature", 0.0)
        self.max_tokens = max_tokens if max_tokens is not None else getattr(inner, "max_tokens", 0)
        self.hits = 0
        self.calls = 0
        self._lock = threading.Lock()
        self._entries: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.cassette.exists():
            return
        with self.cassette.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{self.cassette}:{lineno}: corrupt cassette line") from exc
                self._entries.setdefault(entry["key"], entry["response"])

    def _key(self, system: str, user: str) -> str:
        return request_key(self.model, self.temperature, self.max_tokens, system, user)

    def chat(self, system: str, user: str) -> str:
        key = self._key(system, user)
        with self._lock:
            if self.mode != "record" and key in self._entries:
                self.hits += 1
                return self._entries[key]
        if self.mode == "replay":
            raise LLMCacheMiss(
                f"prompt not on cassette {self.cassette} (key {key[:12]}); "
                "re-record with --llm-mode record or auto"
            )
        assert self.inner is not None  # guaranteed by __init__ for record/auto
        response = self.inner.chat(system, user)
        with self._lock:
            self.calls += 1
            self._entries.setdefault(key, response)
            self.cassette.parent.mkdir(parents=True, exist_ok=True)
            with self.cassette.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({
                    "key": key, "model": self.model, "temperature": self.temperature,
                    "max_tokens": self.max_tokens, "system": system, "user": user,
                    "response": response,
                }) + "\n")
        return response

    def __len__(self) -> int:
        return len(self._entries)
