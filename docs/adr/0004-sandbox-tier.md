# ADR 0004: Subprocess isolation as the sandbox tier for this session

## Status
Accepted (partial — flags future work rather than closing the topic).
Amended by [ADR 0008](0008-sandbox-hardening.md) (audit hook, rlimits, parent-side
comparison) and [ADR 0009](0009-container-sandbox.md) (container tier).

## Context
CLAUDE.md §6: "Subprocess isolation minimum; container preferred." Container
isolation (e.g. gVisor, Docker with dropped capabilities and a network
namespace) is the stronger guarantee but was out of reach for this session:
no container runtime is set up in the execution environment, and standing
one up is infrastructure work orthogonal to the admission-gate/curation
logic this session's time was spent on.

## Decision
`cambium.sandbox.runner.run_in_sandbox` runs candidate source in a child
`python -I -S` process with:
- an explicitly emptied environment (`env={}`) — no inherited PATH, no
  credentials, no proxy variables the candidate could read or use to reach
  the network via an env-configured HTTP client,
- isolated mode (`-I`), which also implies `-S` behavior (no user site
  packages, `PYTHONPATH` ignored), narrowing the importable surface to the
  stdlib,
- a hard wall-clock timeout via `subprocess.run(..., timeout=...)`,
- a scratch `TemporaryDirectory` as cwd, cleaned up after the run.

This is process isolation, not sandboxing of syscalls, filesystem access
beyond cwd, or outbound sockets — a candidate that imports `socket` or
`urllib` directly can still attempt a network call; nothing here blocks the
syscall itself, only removes the ambient credentials/config that would make
such a call useful. Resource caps (memory, CPU) are also not enforced yet —
timeout is the only bound.

## Consequences
- This is the tier every skill in this repo's demo library actually passed
  through; the README should say "subprocess isolation minimum," matching
  CLAUDE.md's own language, not "sandboxed" unqualified.
- Upgrading to container isolation is a drop-in change at exactly one
  seam — `run_in_sandbox`'s subprocess invocation — without touching the
  admission gate, registry, or eval code that calls it, since all of those
  only depend on the `SandboxResult` return contract.
- Future work, tracked here rather than silently assumed: a network
  namespace or explicit `socket` blocklist, and memory/CPU resource limits
  (e.g. via `resource.setrlimit` on POSIX or a Job Object on Windows).
