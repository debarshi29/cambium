# Self-Evolving Agent — Skill Library

Context document for Claude Code. Read this before proposing structure or writing code.

---

## 1. What this project is

An agent that **writes, verifies, and curates its own tool library** across generations of task
attempts. The evolving artifact is the tool/skill set — not prompts, not memory, not weights.

The generation loop is the easy part and is explicitly *not* the contribution. The contribution is
the **admission gate, retrieval, curation, and evaluation** around it. Most public work in this
space (Voyager-style skill libraries, ADAS) generates freely and never establishes that later
generations are actually better than earlier ones on unseen tasks. That gap is the target.

### Thesis

> A skill library only improves an agent if admission is gated on verified reuse, retrieval is
> measured independently, and the library is curated. Ungated growth degrades performance.

The project should be able to support **or refute** this with numbers.

---

## 2. Relationship to prior work

This is a **standalone repo** that consumes the tool/task contract from the completed
`loop-engineering` project as a dependency.

- **Reused:** tool interface, task contract, runner, MLflow wiring.
- **Not reused:** the task pack. `loop-engineering` used research/QA tasks with soft grading.
  The admission gate here needs hard pass/fail, so a new task pack is required.
- **Fixed, not varied:** the base control loop. It is inherited from the winning variant in
  `loop-engineering` and held constant. Varying loop architecture *and* tool mutability at once
  destroys attribution.

> **OPEN DECISION — resolve before Sprint 1 code.** Which loop variant is the base, and was its
> win clean or task-dependent? A reflection loop and a plan-execute loop will interact differently
> with a skill library. Do not hardcode a base loop until this is written down here.

Deliberately **out of scope**: coupling to the `mnemos` procedural-memory system. Leave an
interface hook, not a dependency. Revisit only after this project has an eval story of its own.

---

## 3. Core components

### 3.1 Skill artifact

A versioned record. Minimum fields:

| Field | Purpose |
|---|---|
| `name`, `signature` | Retrieval key and call contract |
| `docstring` | Retrieval text + agent-facing description |
| `source` | Executable body |
| `tests` | Synthesized, must pass in sandbox |
| `provenance` | Task ID and generation that spawned it |
| `stats` | Invocations, success rate, last-used generation |
| `version`, `deprecated` | Curation state |

Skills are immutable once admitted; edits create a new version.

### 3.2 Admission gate

**A skill is not admitted because the agent succeeded while using it.** All of the following must
hold:

1. Executes in sandbox without error, within timeout, no network.
2. Synthesized tests pass.
3. No existing non-deprecated skill already covers the signature (dedup check).
4. **Demonstrated reuse:** succeeds on at least one task other than the one it was extracted from.

Condition 4 is what separates a library from a log. Do not relax it for convenience.

### 3.3 Retrieval

As the library grows, the bottleneck shifts from *does the skill exist* to *can the agent find it*.
Retrieval must be instrumented as a **separate metric**, not folded into task success:

- `retrieval recall@k` against a human-labeled "correct skill" for a subset of tasks.
- Logged per generation, so retrieval decay is visible as the library grows.

### 3.4 Curation

Runs on a schedule (every N generations), not continuously:

- Merge near-duplicate signatures.
- Deprecate by usage decay (unused for N generations + low success rate).
- Hard cap on active library size; deprecation is soft (archived, not deleted) for auditability.

---

## 4. Evaluation — the actual deliverable

### Task pack

~60 tasks, **40 train / 20 held-out**. Held-out tasks are never seen during evolution.
Domain must be **programmatically checkable**: data wrangling, format conversion, API-shaped
transformations, algorithmic problems with unit tests. No fuzzy grading anywhere in the loop.

### The three curves (on held-out set)

1. **library-off** — baseline, fixed toolset.
2. **library-on, evolving** — full system.
3. **library frozen at generation N, evaluated at N+k** — isolates whether later generations
   improved *because of* the library or independently of it.

Curve 3 is the one that makes the result publishable rather than anecdotal.

### Reward-hacking audit

Skills that special-case a specific eval task must be **detected and reported**, not suppressed.
A section of the README on what hacking was found is a feature, not an embarrassment.

### Stretch ablation (Sprint 6, if time)

Re-run the *losing* loop variants from `loop-engineering` with the library attached. Answers
whether a good skill library closes the gap between control-loop architectures. Both outcomes are
interesting: "tooling dominates loop choice" or "loop choice survives tooling."

---

## 5. Sprint plan

Two weeks each, ~5–8 hrs/week.

| Sprint | Deliverable | Done when |
|---|---|---|
| 1 | Task pack, sandbox runner, skill schema + registry | Baseline agent scored on train + held-out, no library |
| 2 | Generation + admission gate | Library grows with provenance; nothing retrieves yet |
| 3 | Retrieval layer + recall@k instrumentation | First end-to-end evolving run |
| 4 | Curation: dedup, decay deprecation, versioning, size cap | Library size stays bounded across 20+ generations |
| 5 | Eval harness, three ablations, hacking audit, MLflow lineage | The three curves exist and are reproducible |
| 6 | Hardening, ADRs, README with curves, demo | Someone else can clone and reproduce |

Sprint 1 is shortened relative to a from-scratch build because the tool/task contract is inherited.

**Sprints 1–2 are where projects like this die.** The failure mode is jumping to generation before
a held-out set exists, after which no one can tell whether anything improved. Do not let Sprint 2
start before the held-out split is frozen and committed.

---

## 6. Engineering constraints

- **Sandboxing is non-negotiable.** Generated code executes. Subprocess isolation minimum;
  container preferred. No network by default. Hard timeouts. Resource caps.
- **Local compute is limited** (6GB VRAM). Assume API-backed models for the agent itself; anything
  requiring local training is out of scope for this project.
- **MLflow 3.0** carries generation lineage — every generation logs library state, scores, and
  retrieval metrics as a linked run.
- Determinism where possible: seed everything, pin model versions, log prompts.

---

## 7. Non-goals

- Prompt/instruction evolution (different project).
- Weight updates or self-training.
- Open-ended or unverifiable task domains.
- Anything requiring `mnemos` to exist.
