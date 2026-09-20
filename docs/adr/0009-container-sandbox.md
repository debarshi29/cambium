# ADR 0009: Container sandbox tier

## Status
Accepted. Closes the "container preferred" half of CLAUDE.md §6 that
[ADR 0004](0004-sandbox-tier.md) deferred.

## Context
After [ADR 0008](0008-sandbox-hardening.md) the subprocess tier blocks the
obvious escapes (network, process creation, writes outside scratch) with a
CPython audit hook, and caps memory/CPU with rlimits on POSIX. Its stated
gaps are structural: audit hooks are not a syscall filter, Windows has no
rlimits, and the process shares the host's filesystem view and network
namespace. CLAUDE.md §6 prefers a container for exactly these reasons.

## Decision
Make the sandbox tier a pluggable **backend** behind the unchanged
`run_in_sandbox` contract, and add a Docker backend.

- `SandboxBackend` protocol: `run(source, fn_name, cases, limits) ->
  SandboxResult`. `SubprocessBackend` is the existing tier;
  `DockerBackend` is new. Both write the *same* three files
  (`write_sandbox_dir`) and are judged by the *same* parent-side code
  (`judge`), so a candidate is held to an identical standard either way.
- Docker flags: `--network none`, `--read-only` root with a 16 MB
  `noexec` `/tmp` tmpfs, only the per-run scratch dir mounted writable,
  `--cap-drop ALL`, `--security-opt no-new-privileges`, `--user
  65534:65534`, cgroup `--memory`/`--memory-swap`, `--cpus 1`,
  `--pids-limit 64`. The audit hook and rlimits still run inside:
  defense in depth, and the same `violation` reporting in both tiers.
- Timeouts: the in-container harness arms a `SIGALRM` wall-clock timer
  (also used by the subprocess tier on POSIX) and reports a clean
  `timeout`; the outer guard adds container start-up grace and `docker
  kill`s on expiry.
- Selection: `CAMBIUM_SANDBOX=subprocess|docker` (default subprocess),
  image via `CAMBIUM_SANDBOX_IMAGE` (pin by digest for reproducibility).
  **No silent downgrade:** an unknown backend, a missing CLI, an
  unreachable daemon, or an unpullable image raises
  `SandboxBackendError` up front; a `docker run` infrastructure failure
  (exit 125-127) raises rather than becoming a failed candidate, because
  "every candidate fails" is indistinguishable from "the generator is
  bad" in the curves.

## Consequences
- The default stays `subprocess`: the reproducible curves must run on a
  laptop with nothing but Python, and container start-up (~0.5-1 s per
  candidate) would multiply the eval run's wall time.
- CI runs a dedicated job with `CAMBIUM_SANDBOX=docker` over the backend
  tests, the full sandbox hardening suite and the skill admission gate,
  so both tiers are held to the same tests on every PR.
- Recommended for any run that drives a live LLM
  (`cambium --sandbox docker ...`): that is where genuinely untrusted code
  shows up.
- Still out of scope: gVisor/Firecracker-class syscall isolation. The
  backend seam is where it would go.
