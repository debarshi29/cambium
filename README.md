<div align="center">

# cambium

**A self-evolving agent whose tool/skill library and prompt library are the
artifacts under study** — admission-gated, retrieved, curated, and
evaluated against held-out tasks.

![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)
![status: scaled demo](https://img.shields.io/badge/status-scaled%20demo-yellow)
![license: unlicensed](https://img.shields.io/badge/license-unlicensed-lightgrey)

</div>

> **Thesis.** A skill and prompt library only improves an agent if
> admission is gated on verified reuse, retrieval is measured
> independently, and the library is curated. Ungated growth degrades
> performance — for tools and for prompts alike.
>
> — [`CLAUDE.md`](./CLAUDE.md) §1, the full project spec

---

## Contents

- [Read this first](#read-this-first)
- [Results](#results)
- [Quickstart](#quickstart)
- [Live LLM path](#live-llm-path)
- [Architecture](#architecture)
- [Design decisions (ADRs)](#design-decisions-adrs)
- [Project history](#project-history)

---

## Read this first

This is a **scaled-down demo run**, built in one continuous session with no
live LLM access — not the full ~60-task, months-long research program
`CLAUDE.md` specifies. Three things to know before trusting any number
below:

| | |
|---|---|
| 🤖 **The curves below are a scripted agent, not a live model.** | The three curves and the attribution ablation measure the library harness — admission gates, retrieval, curation, evaluation — operating on a deterministic generator, not an LLM's code-generation ability. A live path *does* exist ([ADR 0007](docs/adr/0007-live-llm-integration.md)) but is kept out of the reported curves on purpose (determinism, cost, reproducibility). → [ADR 0002](docs/adr/0002-agent-stand-in.md) |
| 📦 **27 tasks, not ~60.** | Read every percentage below as "N of 27," not as a statistically powered result. → [ADR 0003](docs/adr/0003-scaled-demo.md) |
| 🔒 **Subprocess isolation, not containers.** | Candidate code runs in a scrubbed-environment child process with a hard timeout — real isolation, but not the container tier `CLAUDE.md` prefers. → [ADR 0004](docs/adr/0004-sandbox-tier.md) |

[**ADR 0006**](docs/adr/0006-sprint-6-wrapup.md) is the honest scorecard:
what shipped, what didn't, and exactly what the results do and don't
support.

---

## Results

### The three curves + attribution ablation

`CLAUDE.md` §4, measured on the 9-task held-out set:

| curve | held-out solved |
|---|---:|
| **library-off** — fixed toolset, fixed prompts | 2/9 &nbsp;(22%) |
| **library-on, evolving** — generation 4 | **9/9 (100%)** |
| **frozen at generation 2**, evaluated onward | 8/9 &nbsp;(89%) |
| tools-only ablation — skills evolve, prompts fixed | 2/9 &nbsp;(22%) |
| prompts-only ablation — prompts evolve, skills fixed | 2/9 &nbsp;(22%) |

### Generation-by-generation trajectory

The live "both evolving" run:

| generation | train | held-out | active skills | recall@1 | recall@top_k |
|---|---:|---:|---:|---:|---:|
| 1 — default prompts | 5/18 | 2/9 | 0 | — | — |
| 2 — reflector retry budget raised | 18/18 | 8/9 | 7 | 86% | 86% (k=1) |
| 3 — planner top_k raised | 18/18 | **9/9** | 7 | 86% | **100%** (k=2) |
| 4 | 18/18 | 9/9 | 7 | 86% | 100% (k=2) |

### The headline finding

Tools-only and prompts-only **each independently land exactly at the
library-off floor** (2/9) — not partway between library-off and
library-on. Only both evolving together reach 9/9. That's a genuine
interaction effect measured by the actual gate/generation/eval mechanics,
not curve-fit after the fact:

- **Tools-only** never admits a single skill: the reflector's retry budget
  never gets raised (prompts are fixed), so every flawed-first generation
  candidate fails on attempt one with no retry available.
- **Prompts-only** reaches **18/18 on train** — the reflector's raised
  retry budget lets fresh generation solve every category, every time —
  but held-out stays at 2/9, because held-out is scored on retrieval +
  base capability only, never on fresh generation (see
  [ADR 0005](docs/adr/0005-eval-only-scoring.md)). Task-solving capability
  that isn't *persisted as an admitted skill* doesn't transfer. This is
  the single most direct piece of evidence in this repo for the project's
  thesis.
- **Frozen-at-2 (8/9) is strictly worse than live-at-3+ (9/9).** A real,
  measured retrieval collision — two skills' docstrings tie on a shared
  token, and alphabetical order picks the wrong one for `primality` tasks
  (found empirically while testing, not staged — see
  `tests/test_recall.py`) — costs one held-out task until the planner's
  `top_k` gets admitted at generation 3. Continued evolution past a freeze
  point measurably helps.

### Reward-hacking audit

An overfit skill candidate for `run_length_encoding` — hardcodes its
origin task's exact outputs, wired into
[`cambium.agent.generation`](src/cambium/agent/generation.py) specifically
to test this — is proposed twice and **rejected both times** by the
admission gate's reuse check, before a general fix gets admitted from the
category's second task instead. Full findings live in
`results/eval_report.json` under `hacking_audit`, reproduced by
[`cambium.eval.hacking_audit`](src/cambium/eval/hacking_audit.py) on every
eval run — reporting this is a feature of the project, not a suppressed
embarrassment.

---

## Quickstart

Use a virtualenv — don't install project dependencies into your
system/base Python.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest                 # 68 tests, ~80s
```

### Run everything

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
`sqlite:///mlruns.db`; browse it with:

```bash
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

---

## Live LLM path

A real model *can* drive the loop — `cambium.agent.llm_client` +
`cambium.agent.llm_generation` + `cambium.agent.loop.run_task_llm` wire a
Groq-backed model through the exact same seam ADR 0002 left for this
purpose, with zero changes to admission, retrieval, or curation code. It is
kept separate from the results above on purpose: those curves need to be
deterministic and reproducible without an API key, and a live model call is
neither. See [ADR 0007](docs/adr/0007-live-llm-integration.md) for the
full rationale and a verified run (10/10 demo tasks solved, 7 live-
generated skills admitted, real reuse check against a second task each).

Try it yourself:

```bash
cp .env.example .env        # then paste in a Groq API key
python scripts/run_llm_demo.py
```

---

## Architecture

A fixed control loop ([ADR 0001](docs/adr/0001-base-loop-choice.md)):

```
   plan  →  act  →  verify  →  reflect  →  extract
 (planner)         (sandbox)  (reflector)  (critic)
```

Three prompt nodes — `planner`, `reflector`, `critic` — never varied. What
evolves is the tool/skill library the loop retrieves from and the prompt
powering each node:

```
cambium/
├── tasks/        task schema + pack loader (27 tasks, 18 train / 9 heldout)
├── sandbox/      subprocess-isolated runner: exec + verify candidate code
├── skills/       skill schema, versioned registry, admission gate
├── prompts/      prompt schema, versioned-per-node registry, admission gate
├── agent/        base capabilities, scripted generation stand-in, the loop
│                 (+ live Groq path: llm_client, llm_generation, run_task_llm)
├── retrieval/    keyword-overlap index + recall@k instrumentation
├── curation/     dedup, decay deprecation, size cap, version archiving
└── eval/         eval-only scoring, harness (curves + ablation), hacking
                  audit, MLflow lineage
```

Every module's docstring points back to the `CLAUDE.md` section or ADR
that motivates it — start there, not in the source, if something needs
justifying.

---

## Design decisions (ADRs)

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-base-loop-choice.md) | Base control-loop architecture: plan → act → verify → reflect → extract |
| [0002](docs/adr/0002-agent-stand-in.md) | Deterministic scripted stand-in for the LLM-backed agent |
| [0003](docs/adr/0003-scaled-demo.md) | Scaled-down 27-task pack for this session's run |
| [0004](docs/adr/0004-sandbox-tier.md) | Subprocess isolation as the sandbox tier |
| [0005](docs/adr/0005-eval-only-scoring.md) | Node-specific evaluation path for prompt admission |
| [0006](docs/adr/0006-sprint-6-wrapup.md) | Sprint 6 wrap-up: what shipped, what didn't, what's next |
| [0007](docs/adr/0007-live-llm-integration.md) | Live Groq LLM wired through the ADR 0002 seam, kept out of the reported curves |

---

## Project history

Built across six sprints; every sprint landed as its own PR with a real
test suite passing before merge:

- [x] **Sprint 1** — task pack, sandbox runner, skill schema + registry, baseline eval
- [x] **Sprint 2** — admission gates (skills + prompts), candidate generation
- [x] **Sprint 3** — retrieval layer, recall@k, active prompt version selection
- [x] **Sprint 4** — curation: dedup, decay deprecation, size cap
- [x] **Sprint 5** — eval harness: three curves, attribution ablation, hacking audit
- [x] **Sprint 6** — hardening, ADRs, README with results, demo script

See the closed PRs and `docs/adr/` for the decisions — including the ones
that changed course mid-sprint: the 20→27 task pack fix in Sprint 2, the
singleton-registry bug fix in Sprint 4, and the eval-only-scoring fix in
Sprint 5.
