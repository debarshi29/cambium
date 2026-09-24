from cambium.sandbox.cache import CachingBackend, cache_key
from cambium.sandbox.runner import (
    SandboxLimits,
    SandboxResult,
    SubprocessBackend,
    backend_from_env,
    run_in_sandbox,
)

ADD = "def add(a, b):\n    return a + b"
CASES = [{"args": [1, 2], "expected": 3}]


class CountingBackend:
    name = "counting"

    def __init__(self, reason="ok"):
        self.calls = 0
        self.reason = reason

    def run(self, source, fn_name, cases, limits):
        self.calls += 1
        return SandboxResult(self.reason == "ok", self.reason, "", "", 0)


def test_identical_runs_hit_the_cache():
    inner = CountingBackend()
    cache = CachingBackend(inner)
    for _ in range(5):
        assert run_in_sandbox(ADD, "add", CASES, backend=cache).ok
    assert inner.calls == 1
    assert cache.stats.hits == 4 and cache.stats.misses == 1


def test_any_input_change_is_a_miss():
    inner = CountingBackend()
    cache = CachingBackend(inner)
    run_in_sandbox(ADD, "add", CASES, backend=cache)
    run_in_sandbox(ADD + " ", "add", CASES, backend=cache)
    run_in_sandbox(ADD, "add", [{"args": [1, 2], "expected": 4}], backend=cache)
    run_in_sandbox(ADD, "add", CASES, timeout=1.0, backend=cache)
    assert inner.calls == 4


def test_timeouts_and_resource_limits_are_never_cached():
    for reason in ("timeout", "resource_limit"):
        inner = CountingBackend(reason)
        cache = CachingBackend(inner)
        run_in_sandbox(ADD, "add", CASES, backend=cache)
        run_in_sandbox(ADD, "add", CASES, backend=cache)
        assert inner.calls == 2
        assert cache.stats.uncacheable == 2


def test_lru_eviction_bounds_memory():
    cache = CachingBackend(CountingBackend(), maxsize=3)
    for i in range(10):
        run_in_sandbox(f"def f():\n    return {i}", "f", [{"args": [], "expected": i}], backend=cache)
    assert len(cache) == 3


def test_cached_result_is_a_copy():
    cache = CachingBackend(CountingBackend())
    first = run_in_sandbox(ADD, "add", CASES, backend=cache)
    first.stderr = "mutated by caller"
    assert run_in_sandbox(ADD, "add", CASES, backend=cache).stderr == ""


def test_cache_key_depends_on_limits():
    a = cache_key(ADD, "add", CASES, SandboxLimits(memory_mb=128))
    b = cache_key(ADD, "add", CASES, SandboxLimits(memory_mb=256))
    assert a != b


def test_env_flag_wraps_the_backend(monkeypatch):
    monkeypatch.delenv("CAMBIUM_SANDBOX", raising=False)
    monkeypatch.setenv("CAMBIUM_SANDBOX_CACHE", "1")
    backend = backend_from_env()
    assert isinstance(backend, CachingBackend)
    assert isinstance(backend.inner, SubprocessBackend)


def test_real_backend_verdicts_survive_caching():
    cache = CachingBackend(SubprocessBackend())
    assert run_in_sandbox(ADD, "add", CASES, backend=cache).ok
    bad = run_in_sandbox(ADD, "add", [{"args": [1, 2], "expected": 0}], backend=cache)
    again = run_in_sandbox(ADD, "add", [{"args": [1, 2], "expected": 0}], backend=cache)
    assert bad.reason == again.reason == "assertion_failed"
    assert again.stderr == bad.stderr
