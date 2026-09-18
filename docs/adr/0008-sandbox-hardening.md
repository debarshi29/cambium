# ADR 0008: Hardening the subprocess sandbox tier

## Status
Accepted. Amends [ADR 0004](0004-sandbox-tier.md); the container tier is
[ADR 0009](0009-container-sandbox.md).

## Context
ADR 0004 shipped "subprocess isolation minimum" and listed its own gaps: no
network blocking, no resource caps beyond the timeout. Re-reading the
harness with a reward-hacking lens found two worse problems that ADR 0004
did not mention, both of which let a candidate pass the admission gate
**without computing anything**:

1. **Forgeable success marker.** The parent decided "passed" by looking
   for `__SANDBOX_OK__` on stdout. A candidate could print that string at
   import time and `os._exit(0)` before a single case ran.
2. **Comparison ran in the child, with `!=`.** Expected values were shipped
   into the child and compared there. A candidate returning an object
   whose `__eq__`/`__ne__` always agree passes every case.

Neither was exploited by the scripted candidate bank. Both are exactly the
kind of shortcut a live LLM optimizing for "make the test pass" can stumble
into, and CLAUDE.md §4 makes catching that a deliverable.

## Decision
- **Expected values never enter the child.** The child receives call
  arguments only (`cases.json`), calls the function, and reports
  JSON-serialized return values in `result.json`. The parent compares them
  with `values_equal`, a strict structural equality over plain JSON values
  (bools are not numbers). A non-serializable return is a failure, so no
  user-defined `__eq__` ever reaches the comparison. Forging success now
  requires producing the right values -- which is solving the task, or
  hardcoding it, and hardcoding is what the reuse check (§3.2 condition 4)
  catches.
- **Audit hook (PEP 578)** installed in the child before candidate code
  runs, and impossible to remove afterwards. Refuses: sockets, process
  creation and signalling, `ctypes`/native loading, env mutation,
  trace/profile hooks, and filesystem mutation (writes, deletes, renames,
  chmod, ...) outside the per-run scratch directory. A refusal raises
  `SandboxViolation` and yields `reason="violation"`.
- **POSIX resource limits**: address space (`memory_mb`, default 512),
  CPU seconds (timeout + 1), max file size. Hitting one yields
  `reason="resource_limit"`.
- **Bounded output**: stdout/stderr go to files and are read back capped
  (`max_output_bytes`, default 64 KiB).
- **Violations are audit findings.** `cambium.eval.hacking_audit` reports
  a gate rejection caused by a sandbox violation as
  `gate_rejected_sandbox_violation`, alongside the existing overfit
  findings.

Limits are a `SandboxLimits` dataclass; `run_in_sandbox(..., timeout=)`
keeps working unchanged.

## Consequences
- The three curves and the ablation are unchanged (re-run, byte-identical
  `results/eval_report.json`): the scripted candidates never relied on
  either loophole.
- One deliberate semantic change: tuple returns now match list expectations
  (JSON has no tuple), and `True` no longer matches an expected `1`.
- Remaining gaps, stated rather than implied away:
  - Audit hooks are a CPython-level control, not a syscall filter. Code
    that reaches native code by a route we did not anticipate is not
    stopped by them.
  - Windows has no rlimits: the timeout is the only resource bound there.
  - Reads outside the scratch dir are allowed (the environment is empty and
    there is no network, so there is nothing to exfiltrate *to*).
  The container backend (ADR 0009) is the answer to all three, and is the
  recommended tier anywhere Docker is available.
