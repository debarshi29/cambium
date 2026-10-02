# Changelog

All notable changes to this project. Dates are merge dates.

## [1.0.0] - 2026-10-02

### Added
- ADR 0013 (v1.0 wrap-up); HLD/LLD brought in line with the code.

### Added (quality gates)
- Type checking with mypy in CI and pre-commit; 88% coverage gate.
- `Dockerfile` for a reproducible experiment environment, built and smoke-tested in CI.
- `SECURITY.md` (sandbox threat model), `CONTRIBUTING.md`, Dependabot.

### Fixed
- `GroqClient.chat` could `raise None` when configured with negative retries.
- Baseline scoring could hand a `None` source to the sandbox.

## [0.9.0] - 2026-09-30

### Added
- Record/replay cassettes for live LLM calls; `cambium eval --agent llm`
  runs the full eval on the live model and replays it offline (ADR 0012).
- `cambium` CLI: `eval`, `baseline`, `stress`, `llm-demo`, `tasks`,
  `library show|diff`; experiments moved into `cambium.eval.experiments`.
- Curation stress test: 25 generations of noisy near-duplicate proposals,
  curated vs. uncurated (ADR 0011).
- `CachingBackend` for deterministic sandbox verdicts; parallel tests.
- Task pack at spec size: 60 tasks, 40 train / 20 held-out, 20 categories (ADR 0010).
- Docker sandbox tier behind a pluggable backend (ADR 0009).
- Sandbox hardening: audit hook, POSIX rlimits, capped output (ADR 0008).
- Persistent, tamper-checked library snapshots (`cambium.library`).

### Fixed
- Two ways a candidate could forge a sandbox pass (printed success marker;
  always-equal return object). The child no longer sees expected values.
- Curation could delete a category's only skill, and never merged
  paraphrased duplicates (found by the stress test).
- Re-admitting an archived skill's name crashed with a version collision.
- An empty `CachingBackend` was falsy and silently ignored.
- Selecting a sandbox tier from the CLI mutated `os.environ`.

### Changed
- Results at spec scale: library-off 3/20, both evolving 20/20,
  frozen-at-2 19/20, tools-only 3/20, prompts-only 3/20.

## [0.7.0] - 2026-08-23
- Live Groq LLM behind the ADR 0002 seam (ADR 0007); HLD/LLD docs;
  architecture diagram; CI, license, packaging.

## [0.6.0] - 2026-08-15
- Sprints 1-6: task pack, sandbox runner, skill/prompt schemas and
  registries, admission gates, retrieval + recall@k, curation, eval
  harness with the three curves, attribution ablation, hacking audit,
  MLflow lineage.
