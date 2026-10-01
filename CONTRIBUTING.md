# Contributing

## Setup

```bash
uv sync --group dev            # or: python -m venv .venv && pip install -e ".[dev]"
pre-commit install             # optional: ruff + mypy + file checks on commit
```

## The checks CI runs

```bash
uv run ruff check .
uv run mypy
uv run pytest -n auto --cov    # fails under 88% coverage
CAMBIUM_SANDBOX=docker uv run pytest tests/test_sandbox.py tests/test_sandbox_backends.py
```

## Ground rules

These come from the project spec ([`CLAUDE.md`](CLAUDE.md)); PRs that
break them will be asked to change course.

1. **Held-out tasks never enter an admission decision.** Reuse checks
   resolve against train tasks only (`TaskPack.other_task_in_category(...,
   split="train")`).
2. **Don't relax the admission gates for convenience.** Skill condition 4
   (demonstrated reuse) is what separates a library from a log.
3. **Archive, never delete.** Curation flips `deprecated` and records a
   reason; version history is the audit trail.
4. **The control-loop architecture is fixed** ([ADR 0001](docs/adr/0001-base-loop-choice.md)).
   Only tools and per-node prompts evolve.
5. **Report numbers as they come out.** If a change moves a curve, re-run
   `cambium eval`, commit the new `results/`, and say why in the PR,
   including when it moves the wrong way. Reward-hacking findings are
   reported, never suppressed.
6. **Determinism.** The scripted eval must reproduce `results/eval_report.json`
   byte for byte. Seed anything random; record live-LLM runs to a cassette
   (`--llm-cache`).

## Adding tasks

Drop a JSON file in `src/cambium/tasks/data/` (see any existing one). For a
new generated category: two train tasks + one held-out, a two-entry
candidate bank in `cambium.agent.generation` (plausibly wrong, then correct;
the wrong one must fail *every* train task), a docstring, and recall ground
truth. `tests/test_task_pack.py` enforces the shape. See
[ADR 0010](docs/adr/0010-full-task-pack.md).

## Design decisions

Anything that changes what a number means gets an ADR in `docs/adr/`.
