# cambium

A self-evolving agent whose **tool/skill library and prompt library** are the
artifacts under study — admission-gated, retrieved, curated, and evaluated
against held-out tasks. Full project spec: [`CLAUDE.md`](./CLAUDE.md).

> Status: under active development. This README is a stub until Sprint 6;
> see `docs/adr/` for the design decisions made along the way and the sprint
> checklist below for what's actually built vs. planned.

## Sprint checklist

- [x] Sprint 1 — task pack, sandbox runner, skill schema + registry, baseline eval
- [x] Sprint 2 — admission gates (skills + prompts), candidate generation
- [x] Sprint 3 — retrieval layer, recall@k, active prompt version selection
- [x] Sprint 4 — curation: dedup, decay deprecation, size cap
- [x] Sprint 5 — eval harness: three curves, attribution ablation, hacking audit
- [ ] Sprint 6 — hardening, final README with results, demo

## Setup

Use a virtualenv — don't install project dependencies into your system/base
Python.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest
```

## Run the baseline (library-off)

```bash
python scripts/run_baseline.py
```

## Run the Sprint 2 generation + admission demo

```bash
python scripts/run_generation_demo.py
```

Shows the admission gate rejecting an overfit skill candidate (passes its
origin task, fails to generalize) and, once the reflector prompt's retry
budget is raised, admitting the general fix instead.

## Run the Sprint 3 recall@k demo

```bash
python scripts/run_recall_demo.py
```

Shows recall@1 catching a genuine, unplanned retrieval collision (two
skills' docstrings tie on a shared token, alphabetical order picks the
wrong one), decaying further as decoy skills are added, and recovering at
higher k — the mechanism the planner prompt's `top_k` slot controls.

## Run the Sprint 4 curation demo

```bash
python scripts/run_curation_demo.py
```

Shows all four curation passes in one run: near-duplicate skill merge,
usage-decay deprecation, a hard size cap, and archiving superseded prompt
versions — all soft deprecation, nothing deleted from version history.

## Run the Sprint 5 eval harness (the three curves + attribution ablation)

```bash
python scripts/run_eval.py
```

Writes `results/eval_report.json` and logs full generation lineage to
MLflow (`sqlite:///mlruns.db` — `mlflow ui --backend-store-uri
sqlite:///mlruns.db` to browse it). Headline result from this run:

| curve | held-out (9 tasks) |
|---|---|
| library-off | 2/9 (22%) |
| library-on, evolving (gen 4) | 9/9 (100%) |
| frozen at generation 2 | 8/9 (89%) — strictly worse than continuing to gen 3+ |
| tools-only ablation | 2/9 — identical to library-off |
| prompts-only ablation | 2/9 — identical to library-off, despite 18/18 on train |

Tools-only and prompts-only *each independently* land exactly at the
library-off floor; only both together reach 9/9. See
[`docs/adr/0005-eval-only-scoring.md`](docs/adr/0005-eval-only-scoring.md)
for why prompts-only masters train (18/18) but gains nothing on held-out —
that gap is the demo's most direct evidence for the project's thesis.

## Important caveats (read before trusting any number)

- **The agent is a scripted stand-in, not a live LLM call** — see
  [`docs/adr/0002-agent-stand-in.md`](docs/adr/0002-agent-stand-in.md). What
  this repo measures is the library harness (admission, retrieval, curation,
  eval), not code-generation quality.
- **The task pack is scaled down** from the spec's 60 tasks to 20 — see
  [`docs/adr/0003-scaled-demo.md`](docs/adr/0003-scaled-demo.md).
- **Sandboxing is subprocess-isolation tier**, not container tier — see
  [`docs/adr/0004-sandbox-tier.md`](docs/adr/0004-sandbox-tier.md).
