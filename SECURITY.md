# Security

cambium **executes generated code by design**: every skill candidate,
whether from the scripted stand-in or a live LLM, runs in a sandbox before
it can be admitted. This file is the threat model for that sandbox and how
to report problems with it.

## Reporting

Please open a private security advisory on GitHub
(*Security → Report a vulnerability*) rather than a public issue. Include
the candidate source that escapes or misleads the sandbox, the sandbox tier
(`subprocess` or `docker`), OS, and Python version.

## Threat model

**Adversary:** candidate code that is wrong, or that is shaped (deliberately
or by an optimizing generator) to *look* right to the admission gate.

**Assets:** the host (filesystem, network, credentials), and the integrity
of admission decisions, which are the project's evidence.

| Guarantee | subprocess tier | docker tier |
|---|---|---|
| Child never sees expected outputs; verdict computed by the parent with strict JSON equality | ✅ | ✅ |
| No inherited environment (no API keys, proxies, PATH) | ✅ | ✅ |
| Network blocked | audit hook (CPython-level) | `--network none` (kernel) |
| Process creation / signals / `ctypes` blocked | audit hook | audit hook + `--cap-drop ALL`, `--pids-limit` |
| Filesystem writes outside the scratch dir blocked | audit hook | audit hook + read-only root |
| Memory / CPU caps | `setrlimit` on POSIX only | cgroups, every host OS |
| Wall-clock timeout | ✅ | ✅ |
| Reads outside the scratch dir blocked | ❌ | ✅ (only the scratch dir is mounted) |

Details and rationale: [ADR 0008](docs/adr/0008-sandbox-hardening.md)
(subprocess hardening, including two result-forgery holes it closed) and
[ADR 0009](docs/adr/0009-container-sandbox.md) (container tier).

**Use the docker tier for any run that drives a live model**
(`cambium --sandbox docker ...` / `CAMBIUM_SANDBOX=docker`). The subprocess
tier's audit hook is a CPython-level control, not a syscall filter.

## Out of scope

- gVisor/Firecracker-class syscall isolation (the backend seam in
  `cambium.sandbox.runner` is where it would go).
- Docker-in-docker: the published `Dockerfile` runs the subprocess tier
  inside the container, with the container as the outer boundary.

## Secrets

`GROQ_API_KEY` is read from the environment or a git-ignored `.env`. It is
never passed to sandboxed code. LLM cassettes (`--llm-cache`) contain
prompts and responses, not keys.
