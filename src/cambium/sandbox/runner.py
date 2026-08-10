"""Sandbox runner: executes candidate skill source against a fixed set of
cases in a subprocess, out-of-process from this agent.

CLAUDE.md §6: "Sandboxing is non-negotiable. Generated code executes.
Subprocess isolation minimum; container preferred. No network by default.
Hard timeouts. Resource caps."

This is the "subprocess isolation minimum" tier: candidate source runs as a
child `python -I -S` process (isolated mode: ignores PYTHONPATH/user site,
no site-packages import), with a hard wall-clock timeout and a scrubbed
environment. It does not sandbox syscalls or filesystem access the way a
container would — that upgrade is flagged in docs/adr/0004-sandbox-tier.md
as future work, not silently assumed.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_OK_MARKER = "__SANDBOX_OK__"
DEFAULT_TIMEOUT = 5.0


@dataclass
class SandboxResult:
    ok: bool
    reason: str  # "ok" | "assertion_failed" | "exception" | "timeout"
    stdout: str
    stderr: str
    returncode: int


_TEST_LOOP_TEMPLATE = """\
_cases = __CASES__
for _i, _c in enumerate(_cases):
    _args = _c.get("args", [])
    _kwargs = _c.get("kwargs", {})
    _expected = _c["expected"]
    _got = __FN_NAME__(*_args, **_kwargs)
    if _got != _expected:
        raise AssertionError(
            "case %d failed: args=%r kwargs=%r expected=%r got=%r"
            % (_i, _args, _kwargs, _expected, _got)
        )
print("__OK_MARKER__")
"""


def _build_harness(source: str, fn_name: str, cases: list) -> str:
    # Concatenate rather than dedent-over-interpolate: `source` is arbitrary
    # candidate code with its own indentation, so textwrap.dedent() on the
    # combined text would use *its* leading whitespace as the common prefix
    # and corrupt the fixed harness lines around it. Plain string
    # substitution (no f-string, no .format — candidate source may itself
    # contain `{`/`}`) keeps the two pieces independent.
    test_loop = (
        _TEST_LOOP_TEMPLATE
        .replace("__CASES__", repr(cases))
        .replace("__FN_NAME__", fn_name)
        .replace("__OK_MARKER__", _OK_MARKER)
    )
    return source.rstrip() + "\n\n" + test_loop


def run_in_sandbox(
    source: str,
    fn_name: str,
    cases: list,
    timeout: float = DEFAULT_TIMEOUT,
) -> SandboxResult:
    """Run `source` (must define `fn_name`) against `cases` in a subprocess.

    `cases` is a list of {"args": [...], "kwargs": {...}, "expected": ...}
    dicts (see cambium.tasks.schema.TaskCase.to_dict).
    """
    harness = _build_harness(source, fn_name, cases)

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "candidate.py"
        script_path.write_text(harness, encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env={},  # no inherited env: no proxy vars, no credentials, no PATH
            )
        except subprocess.TimeoutExpired as e:
            return SandboxResult(
                ok=False,
                reason="timeout",
                stdout=(e.stdout or ""),
                stderr=f"exceeded {timeout}s timeout",
                returncode=-1,
            )

        if proc.returncode == 0 and _OK_MARKER in proc.stdout:
            return SandboxResult(True, "ok", proc.stdout, proc.stderr, 0)

        reason = "assertion_failed" if "AssertionError" in proc.stderr else "exception"
        return SandboxResult(False, reason, proc.stdout, proc.stderr, proc.returncode)
