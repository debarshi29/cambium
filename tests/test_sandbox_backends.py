"""Backend selection + the Docker tier. Docker tests skip when no daemon is
reachable; CI runs them in a dedicated job (and re-runs tests/test_sandbox.py
with CAMBIUM_SANDBOX=docker, so both tiers face the same hardening suite)."""
import pytest

from cambium.sandbox import runner
from cambium.sandbox.docker_backend import DockerBackend
from cambium.sandbox.runner import (
    SandboxBackendError,
    SandboxLimits,
    SubprocessBackend,
    backend_from_env,
    run_in_sandbox,
)

HAS_DOCKER = DockerBackend.is_available()
needs_docker = pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon not available")


def test_default_backend_is_subprocess(monkeypatch):
    monkeypatch.delenv("CAMBIUM_SANDBOX", raising=False)
    assert isinstance(backend_from_env(), SubprocessBackend)


def test_unknown_backend_is_an_error_not_a_downgrade(monkeypatch):
    monkeypatch.setenv("CAMBIUM_SANDBOX", "chroot")
    with pytest.raises(SandboxBackendError):
        backend_from_env()


def test_docker_requested_but_unusable_fails_loudly(monkeypatch):
    monkeypatch.setenv("CAMBIUM_SANDBOX", "docker")
    monkeypatch.setenv("CAMBIUM_DOCKER", "definitely-not-a-docker-binary")
    with pytest.raises(SandboxBackendError):
        backend_from_env()


def test_explicit_backend_argument_wins():
    calls = []

    class Recording:
        name = "recording"

        def run(self, source, fn_name, cases, limits):
            calls.append((fn_name, limits.timeout))
            return runner.SandboxResult(True, "ok", "", "", 0)

    r = run_in_sandbox("def f(): return 1", "f", [{"args": [], "expected": 1}],
                       timeout=2.0, backend=Recording())
    assert r.ok and calls == [("f", 2.0)]


def test_docker_command_has_the_isolation_flags(tmp_path):
    cmd = DockerBackend().command(tmp_path, "cambium-sbx-test", SandboxLimits(memory_mb=256))
    joined = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL",
                 "--security-opt no-new-privileges", "--user 65534:65534",
                 "--memory 256m", "--memory-swap 256m", "--pids-limit"):
        assert flag in joined, flag


@needs_docker
def test_docker_backend_runs_a_passing_candidate():
    r = run_in_sandbox("def add(a, b):\n    return a + b", "add",
                       [{"args": [1, 2], "expected": 3}], backend=DockerBackend())
    assert r.ok, r.stderr


@needs_docker
def test_docker_backend_reports_wrong_answers():
    r = run_in_sandbox("def add(a, b):\n    return a - b", "add",
                       [{"args": [1, 2], "expected": 3}], backend=DockerBackend())
    assert r.reason == "assertion_failed"


@needs_docker
def test_docker_backend_has_no_network_interface_but_loopback():
    """The kernel-level fact behind --network none, independent of the
    audit hook: the only interface the container can see is `lo`."""
    src = (
        "def ifaces():\n"
        "    lines = open('/proc/net/dev').read().splitlines()[2:]\n"
        "    return sorted(ln.split(':')[0].strip() for ln in lines if ln.strip())\n"
    )
    r = run_in_sandbox(src, "ifaces", [{"args": [], "expected": ["lo"]}], backend=DockerBackend())
    assert r.ok, r.stderr


@needs_docker
def test_docker_backend_times_out():
    src = "def slow():\n    import time\n    time.sleep(30)"
    r = run_in_sandbox(src, "slow", [{"args": [], "expected": None}], timeout=1.0, backend=DockerBackend())
    assert r.reason == "timeout"


@needs_docker
def test_docker_backend_enforces_memory_cap():
    src = "def f():\n    x = bytearray(1024 * 1024 * 1024)\n    return len(x)\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}],
                       limits=SandboxLimits(memory_mb=128), backend=DockerBackend())
    assert r.reason == "resource_limit"
