"""Memoizing sandbox backend.

An evolution run executes the *same* (source, fn_name, cases) triple many
times: every generation re-runs every retrieved skill against every train
task, prompt admission re-evaluates the regression subset for both the
candidate and its parent, and held-out scoring repeats per generation and
per ablation arm. Each execution is a fresh interpreter (~90 ms on a
laptop, far more on the docker tier), and with scripted candidates the
answer never changes.

`CachingBackend` wraps any backend and memoizes results by a content hash
of everything that can affect the outcome: source, function name, the
full cases (args *and* expected values), and the limits. Only
**deterministic verdicts** are cached -- `ok`, `assertion_failed`,
`exception`, `violation`. `timeout` and `resource_limit` depend on machine
load, so they are always re-run.

Caveat, stated plainly: caching assumes the candidate is a pure function
of its inputs. Scripted candidates are; a live-LLM candidate that calls
`random` or reads the clock might not be. Caching is therefore opt-in
(`CAMBIUM_SANDBOX_CACHE=1`, or `cambium --sandbox-cache`) and the
reproducible eval scripts turn it on explicitly.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace

from cambium.sandbox.runner import SandboxBackend, SandboxLimits, SandboxResult

CACHEABLE_REASONS = frozenset({"ok", "assertion_failed", "exception", "violation"})


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    uncacheable: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


def cache_key(source: str, fn_name: str, cases: list, limits: SandboxLimits) -> str:
    payload = json.dumps(
        {"source": source, "fn_name": fn_name, "cases": cases, "limits": asdict(limits)},
        sort_keys=True,
        default=repr,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachingBackend:
    def __init__(self, inner: SandboxBackend, maxsize: int = 8192):
        self.inner = inner
        self.maxsize = maxsize
        self.name = f"{inner.name}+cache"
        self.stats = CacheStats()
        self._entries: OrderedDict[str, SandboxResult] = OrderedDict()
        self._lock = threading.Lock()

    def run(self, source: str, fn_name: str, cases: list, limits: SandboxLimits) -> SandboxResult:
        key = cache_key(source, fn_name, cases, limits)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                self.stats.hits += 1
                return replace(cached)  # callers get their own copy

        result = self.inner.run(source, fn_name, cases, limits)

        with self._lock:
            if result.reason in CACHEABLE_REASONS:
                self.stats.misses += 1
                self._entries[key] = replace(result)
                if len(self._entries) > self.maxsize:
                    self._entries.popitem(last=False)
            else:
                self.stats.uncacheable += 1
        return result

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.stats = CacheStats()

    def __len__(self) -> int:
        return len(self._entries)


def enable_default_cache() -> CachingBackend:
    """Wrap the process-wide default backend in a cache (idempotent).
    Used by the reproducible, scripted-candidate entry points."""
    from cambium.sandbox.runner import get_default_backend, set_default_backend

    current = get_default_backend()
    if isinstance(current, CachingBackend):
        return current
    cached = CachingBackend(current)
    set_default_backend(cached)
    return cached
