"""Sandbox runner: executes candidate skill source against a fixed set of
cases in a subprocess, out-of-process from this agent.

CLAUDE.md §6: "Sandboxing is non-negotiable. Generated code executes.
Subprocess isolation minimum; container preferred. No network by default.
Hard timeouts. Resource caps."

This is the subprocess tier (docs/adr/0004, hardened per docs/adr/0008).
Each run gets a fresh scratch directory holding three files -- the
candidate, a harness (`harness_template.py`), and the call arguments --
and a `python -I -S` child with a scrubbed environment and a hard
wall-clock timeout. Inside the child, before any candidate code runs, the
harness:

- applies POSIX resource limits (address space, CPU seconds, file size),
- installs a non-removable audit hook (PEP 578) that refuses network,
  process creation, native-code loading, and filesystem mutation outside
  the scratch directory.

**The child never sees expected outputs.** It receives call arguments
only, and reports back JSON-serialized return values; the comparison
against expected values happens here, in the parent, with a strict
type-aware equality. Earlier versions shipped the expected values into the
child and trusted a printed "OK" marker, which a candidate could forge
(print the marker and `os._exit(0)`) or sidestep (return an object whose
`__eq__` always says True). Neither is possible now: to pass, a candidate
has to actually produce the right values.

What this still is *not*: a syscall-level sandbox. Audit hooks are a
CPython-level control, Windows has no rlimits, and reads outside the
scratch dir are allowed (the environment is empty, and there is no network
to exfiltrate over). docs/adr/0008 lists the remaining gaps; the container
backend (cambium.sandbox.docker_backend) closes most of them.
"""
from __future__ import annotations

import json
import math
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 5.0
_HARNESS_SOURCE = (Path(__file__).parent / "harness_template.py").read_text(encoding="utf-8")


@dataclass(frozen=True)
class SandboxLimits:
    """Per-run resource caps. Memory/CPU/file-size are enforced on POSIX
    only (setrlimit); the timeout is enforced everywhere."""

    timeout: float = DEFAULT_TIMEOUT
    memory_mb: int = 512
    max_output_bytes: int = 64 * 1024

    def child_config(self) -> dict:
        return {
            "memory_bytes": self.memory_mb * 1024 * 1024,
            "cpu_seconds": max(1, math.ceil(self.timeout)) + 1,
            "file_size_bytes": max(self.max_output_bytes, 1024 * 1024),
        }


DEFAULT_LIMITS = SandboxLimits()


@dataclass
class SandboxResult:
    ok: bool
    # "ok" | "assertion_failed" | "exception" | "timeout" | "violation" | "resource_limit"
    reason: str
    stdout: str
    stderr: str
    returncode: int


def values_equal(got, expected) -> bool:
    """Strict structural equality over JSON values. Differs from `==` in
    one deliberate way: bools are not numbers (`True != 1`), so a function
    that should return a count can't pass by returning a truthy flag."""
    if isinstance(got, bool) or isinstance(expected, bool):
        return type(got) is type(expected) and got == expected
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        return got == expected
    if type(got) is not type(expected):
        return False
    if isinstance(got, list):
        return len(got) == len(expected) and all(map(values_equal, got, expected))
    if isinstance(got, dict):
        return got.keys() == expected.keys() and all(values_equal(got[k], expected[k]) for k in got)
    return got == expected


def _normalize(value):
    """Expected values go through the same JSON round trip the child's
    return values do (tuples become lists, keys become strings)."""
    return json.loads(json.dumps(value))


def _read_capped(path: Path, cap: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as fh:
        data = fh.read(cap + 1)
    text = data[:cap].decode("utf-8", errors="replace")
    return text + ("\n[... output truncated ...]" if len(data) > cap else "")


def _killed_by_limit(returncode: int) -> bool:
    limit_signals = {
        getattr(signal, name) for name in ("SIGXCPU", "SIGXFSZ", "SIGKILL", "SIGSEGV")
        if hasattr(signal, name)
    }
    return returncode < 0 and -returncode in limit_signals


def write_sandbox_dir(workdir: Path, source: str, fn_name: str, cases: list) -> None:
    """Lay out the three files the harness expects. Shared with the
    container backend so both tiers run byte-identical harness code."""
    (workdir / "candidate.py").write_text(source, encoding="utf-8")
    (workdir / "harness.py").write_text(_HARNESS_SOURCE, encoding="utf-8")
    call_specs = [{"args": list(c.get("args", [])), "kwargs": dict(c.get("kwargs", {}))} for c in cases]
    (workdir / "cases.json").write_text(
        json.dumps({"fn_name": fn_name, "cases": call_specs}), encoding="utf-8"
    )


def judge(
    workdir: Path, cases: list, stdout: str, stderr: str, returncode: int
) -> SandboxResult:
    """Turn a finished child run into a SandboxResult by comparing the
    child's reported return values against `cases`' expected values."""
    result_path = workdir / "result.json"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None

    if payload is None:
        reason = "resource_limit" if _killed_by_limit(returncode) else "exception"
        note = f"sandbox: child exited {returncode} without reporting results"
        return SandboxResult(False, reason, stdout, (stderr + "\n" + note).strip(), returncode)

    error = payload.get("load_error")
    results = payload.get("results", [])
    if error is None:
        for i, (case, res) in enumerate(zip(cases, results, strict=False)):
            if "error" in res:
                error = res["error"]
                break
            expected = _normalize(case["expected"])
            if not values_equal(res["value"], expected):
                msg = (
                    f"AssertionError: case {i} failed: args={list(case.get('args', []))!r} "
                    f"kwargs={dict(case.get('kwargs', {}))!r} expected={expected!r} "
                    f"got={res['value']!r}"
                )
                return SandboxResult(False, "assertion_failed", stdout, (stderr + "\n" + msg).strip(), 1)
        else:
            if len(results) == len(cases):
                return SandboxResult(True, "ok", stdout, stderr, 0)
            note = f"sandbox: only {len(results)}/{len(cases)} cases reported"
            return SandboxResult(False, "exception", stdout, (stderr + "\n" + note).strip(), 1)

    if error.get("violation"):
        reason = "violation"
    elif error.get("memory"):
        reason = "resource_limit"
    else:
        reason = "exception"
    msg = f"{error.get('type')}: {error.get('message')}"
    if msg not in stderr:
        stderr = (stderr + "\n" + msg).strip()
    return SandboxResult(False, reason, stdout, stderr, returncode or 1)


def run_in_sandbox(
    source: str,
    fn_name: str,
    cases: list,
    timeout: float | None = None,
    limits: SandboxLimits | None = None,
) -> SandboxResult:
    """Run `source` (must define `fn_name`) against `cases` in a subprocess.

    `cases` is a list of {"args": [...], "kwargs": {...}, "expected": ...}
    dicts (see cambium.tasks.schema.TaskCase.to_dict). `timeout`, if given,
    overrides `limits.timeout` (kept for backward compatibility).
    """
    limits = limits or DEFAULT_LIMITS
    if timeout is not None:
        limits = SandboxLimits(timeout=timeout, memory_mb=limits.memory_mb,
                               max_output_bytes=limits.max_output_bytes)

    with tempfile.TemporaryDirectory(prefix="cambium-sbx-") as tmp:
        workdir = Path(tmp).resolve()
        write_sandbox_dir(workdir, source, fn_name, cases)
        out_path, err_path = workdir / "stdout.txt", workdir / "stderr.txt"

        with out_path.open("wb") as out, err_path.open("wb") as err:
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-S", "harness.py", json.dumps(limits.child_config())],
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    timeout=limits.timeout,
                    cwd=workdir,
                    env={},  # no inherited env: no proxy vars, no credentials, no PATH
                )
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                returncode = None

        stdout = _read_capped(out_path, limits.max_output_bytes)
        stderr = _read_capped(err_path, limits.max_output_bytes)
        if returncode is None:
            return SandboxResult(False, "timeout", stdout, f"exceeded {limits.timeout}s timeout", -1)
        return judge(workdir, cases, stdout, stderr, returncode)
