# cambium

A self-evolving agent whose **tool/skill library and prompt library** are
the artifacts under study — admission-gated, retrieved, curated, and
evaluated against held-out tasks.

> **Thesis** (CLAUDE.md §1): a skill and prompt library only improves an
> agent if admission is gated on verified reuse, retrieval is measured
> independently, and the library is curated. Ungated growth degrades
> performance — for tools and for prompts alike.

Full project spec: [`CLAUDE.md`](./CLAUDE.md). All design decisions along
the way: [`docs/adr/`](./docs/adr/).

## Read this first

This is a scaled-down demo run, built in one continuous session with no
live LLM access — not the full ~60-task, months-long research program
CLAUDE.md specifies. Three things to know before trusting any number below:

1. **The agent is a scripted stand-in, not a live model call.** What this
   repo measures is the library harness — admission gates, retrieval,
   curation, evaluation — operating on a deterministic generator, not an
   LLM's code-generation or self-improvement ability.
   [`docs/adr/0002`](docs/adr/0002-agent-stand-in.md).
2. **The task pack is 27 tasks, not ~60.** Read percentages as "N of 27."
   [`docs/adr/0003`](docs/adr/0003-scaled-demo.md).
3. **Sandboxing is subprocess-isolation tier, not container tier.**
   [`docs/adr/0004`](docs/adr/0004-sandbox-tier.md).

[`docs/adr/0006`](docs/adr/0006-sprint-6-wrapup.md) is the honest scorecard:
what shipped, what didn't, and what the results do and don't support.

## Results

The three curves + the tools-vs-prompts attribution ablation (CLAUDE.md
§4), held-out set, 9 tasks:

| curve | held-out solved |
|---|---|
| **library-off** (fixed toolset, fixed prompts) | 2/9 (22%) |
| **library-on, evolving** (generation 4) | **9/9 (100%)** |
| **frozen at generation 2**, evaluated onward | 8/9 (89%) |
| tools-only ablation (skills evolve, prompts fixed) | 2/9 (22%) |
| prompts-only ablation (prompts evolve, skills fixed) | 2/9 (22%) |

Generation-by-generation, the live "both evolving" run:

| generation | train | held-out | active skills | recall@1 | recall@top_k |
|---|---|---|---|---|---|
| 1 (default prompts) | 5/18 | 2/9 | 0 | — | — |
| 2 (reflector retry budget raised) | 18/18 | 8/9 | 7 | 86% | 86% (k=1) |
| 3 (planner top_k raised) | 18/18 | **9/9** | 7 | 86% | **100%** (k=2) |
| 4 | 18/18 | 9/9 | 7 | 86% | 100% (k=2) |

### The headline finding

Tools-only and prompts-only **each independently land exactly at the
library-off floor** (2/9) — not partway between library-off and
library-on. Only both evolving together reach 9/9. That's a genuine
interaction effect measured by the actual gate/generation/eval mechanics,
not curve-fit after the fact:

- **Tools-only** never admits a single skill: the reflector's retry budget
  never gets raised (prompts are fixed), and every flawed-first generation
  candidate fails on attempt one with no retry available.
- **Prompts-only** reaches **18/18 on train** — the reflector's raised
  retry budget lets fresh generation solve every category, every time —
  but held-out stays at 2/9, because held-out is scored on retrieval +
  base capability only, never on fresh generation (see
  [`docs/adr/0005`](docs/adr/0005-eval-only-scoring.md)). Task-solving
  capability that isn't *persisted as an admitted skill* doesn't transfer.
  This is the single most direct piece of evidence in this repo for the
  project's thesis.
- **Frozen-at-2 (8/9) is strictly worse than live-at-3+ (9/9)**: a real,
  measured retrieval collision (two skills' docstrings tie on a shared
  token; alphabetical order picks the wrong one for `primality` tasks —
  found empirically, not staged, see `tests/test_recall.py`) costs one
  held-out task until the planner's `top_k` gets admitted at generation 3.
  Continued evolution past a freeze point measurably helps.

### Reward-hacking audit

An overfit skill candidate for `run_length_encoding` (hardcodes its origin
task's exact outputs, wired into
[`cambium.agent.generation`](src/cambium/agent/generation.py) specifically
to test this) is proposed twice and **rejected both times** by the
admission gate's reuse check, before a general fix gets admitted from the
category's second task instead. Full findings in `results/eval_report.json`
under `hacking_audit`, reproduced by
[`cambium.eval.hacking_audit`](src/cambium/eval/hacking_audit.py) on every
eval run — this is a feature, not a suppressed embarrassment.

## Sprint checklist

- [x] Sprint 1 — task pack, sandbox runner, skill schema + registry, baseline eval
- [x] Sprint 2 — admission gates (skills + prompts), candidate generation
- [x] Sprint 3 — retrieval layer, recall@k, active prompt version selection
- [x] Sprint 4 — curation: dedup, decay deprecation, size cap
- [x] Sprint 5 — eval harness: three curves, attribution ablation, hacking audit
- [x] Sprint 6 — hardening, ADRs, README with results, demo script

## Setup

Use a virtualenv — don't install project dependencies into your system/base
Python.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest                 # 68 tests, ~80s
```

## Run everything

```bash
python scripts/demo.py
```

Runs the baseline, the generation+admission demo, the recall@k demo, the
curation demo, and the full eval harness in sequence. Individually:

| script | what it shows |
|---|---|
| `scripts/run_baseline.py` | curve 1: library-off, no admission/generation machinery at all |
| `scripts/run_generation_demo.py` | the admission gate rejecting an overfit skill, then admitting the general fix once the reflector's retry budget is raised |
| `scripts/run_recall_demo.py` | recall@1 catching a real retrieval collision, decaying further with decoys, recovering at higher k |
| `scripts/run_curation_demo.py` | all four curation passes: dedup, decay, size cap, prompt version archiving |
| `scripts/run_eval.py` | the full eval harness: all three curves, the attribution ablation, the hacking audit, MLflow lineage |

`scripts/run_eval.py` logs full generation lineage to
`sqlite:///mlruns.db`; browse it with
`mlflow ui --backend-store-uri sqlite:///mlruns.db`.

## Architecture

Fixed control loop (`docs/adr/0001`): **plan → act → verify → reflect →
extract**, three prompt nodes (`planner`, `reflector`, `critic`), never
varied. What evolves:

```
cambium/
├── tasks/        task schema + pack loader (27 tasks, 18 train / 9 heldout)
├── sandbox/      subprocess-isolated runner: exec + verify candidate code
├── skills/       skill schema, versioned registry, admission gate
├── prompts/      prompt schema, versioned-per-node registry, admission gate
├── agent/        base capabilities, scripted generation stand-in, the loop
├── retrieval/    keyword-overlap index + recall@k instrumentation
├── curation/     dedup, decay deprecation, size cap, version archiving
└── eval/         eval-only scoring, harness (curves + ablation), hacking
                  audit, MLflow lineage
```

Every module's docstring points back to the CLAUDE.md section or ADR that
motivates it — start there, not in the source, if something needs
justifying.

## Project history

Built across six sprints; every sprint landed as its own PR with a real
test suite passing before merge — see the closed PRs and `docs/adr/` for
the decisions (including the ones that changed course mid-sprint: the
20→27 task pack fix in Sprint 2, the singleton-registry bug fix in Sprint 4,
the eval-only-scoring fix in Sprint 5).
