# Self-Evolving Agent — Skill & Prompt Library

Context document for Claude Code. Read this before proposing structure or writing code.

---

## 1. What this project is

An agent that **writes, verifies, and curates its own tool library and prompt library** across
generations of task attempts. The evolving artifacts are the tool/skill set *and* the agent's own
prompts — not memory, not weights.

The generation loop is the easy part and is explicitly *not* the contribution. The contribution is
the **admission gate, retrieval, curation, and evaluation** around both artifact types. Most public
work in this space (Voyager-style skill libraries, ADAS, prompt-optimization frameworks like
DSPy/OPRO) generates freely and never establishes that later generations are actually better than
earlier ones on unseen tasks. That gap is the target.

### Thesis

> A skill and prompt library only improves an agent if admission is gated on verified reuse,
> retrieval is measured independently, and the library is curated. Ungated growth degrades
> performance — for tools and for prompts alike.

The project should be able to support **or refute** this with numbers, and should be able to say
*which* artifact type (tools, prompts, or their interaction) is doing the work.

---

## 2. Relationship to prior work

This is a **standalone repo** that consumes the tool/task contract from the completed
`loop-engineering` project as a dependency.

- **Reused:** tool interface, task contract, runner, MLflow wiring.
- **Not reused:** the task pack. `loop-engineering` used research/QA tasks with soft grading.
  The admission gate here needs hard pass/fail, so a new task pack is required.
- **Fixed, not varied:** the base control loop *architecture*. It is inherited from the winning
  variant in `loop-engineering` and held constant. What evolves are the tools available to the
  loop and the prompts populating the loop's nodes (planner, reflector, critic, etc.) — not the
  graph of nodes and edges itself. Varying loop architecture *and* tool/prompt mutability at once
  destroys attribution.

> **OPEN DECISION — resolve before Sprint 1 code.** Which loop variant is the base, and was its
> win clean or task-dependent? A reflection loop and a plan-execute loop will interact differently
> with a skill library and expose a different set of prompt nodes to evolve. Do not hardcode a
> base loop until this is written down here.

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

### 3.2 Skill admission gate

**A skill is not admitted because the agent succeeded while using it.** All of the following must
hold:

1. Executes in sandbox without error, within timeout, no network.
2. Synthesized tests pass.
3. No existing non-deprecated skill already covers the signature (dedup check).
4. **Demonstrated reuse:** succeeds on at least one task other than the one it was extracted from.

Condition 4 is what separates a library from a log. Do not relax it for convenience.

### 3.3 Prompt artifact

A versioned record, structurally parallel to the skill artifact.

| Field | Purpose |
|---|---|
| `name`, `node` | Which loop node/role the prompt targets (e.g. planner, reflector, critic) |
| `template` | The prompt text, with variable slots |
| `docstring` | Retrieval text + rationale for the mutation |
| `eval_task_ids` | Tasks used to measure this variant against its parent |
| `provenance` | Parent prompt version, task/generation that spawned the mutation |
| `stats` | Invocations, win rate vs. parent, last-used generation |
| `version`, `deprecated` | Curation state |

Prompts are versioned **per loop node**, not globally — a planner prompt and a reflector prompt
evolve independently of each other. Immutable once admitted; edits create a new version, same
discipline as skills.

### 3.4 Prompt admission gate

A prompt variant is not admitted because one run went well. All of the following must hold:

1. Evaluated on a fixed regression subset of train tasks — not just the task that produced it.
2. **Demonstrated improvement:** matches or beats the parent prompt's success rate on that
   subset, with no task-level regression beyond a tolerance threshold.
3. **Demonstrated reuse:** the improvement holds across more than one task. A prompt tuned to one
   task's exact phrasing is not admitted — this is the prompt analogue of skill condition 4.
4. Dedup check: not a near-duplicate (embedding or edit distance) of an existing non-deprecated
   variant for the same node.

Condition 1's regression subset is the prompt analogue of "tests pass in sandbox" — prompts have
no unit tests, so the regression subset *is* the sandbox.

### 3.5 Retrieval

As the skill library grows, the bottleneck shifts from *does the skill exist* to *can the agent
find it*. Retrieval must be instrumented as a **separate metric**, not folded into task success:

- `retrieval recall@k` against a human-labeled "correct skill" for a subset of tasks.
- Logged per generation, so retrieval decay is visible as the library grows.

Prompt retrieval is structurally simpler and does not get this treatment: each loop node runs
exactly one **active** (current-best, admitted) prompt version at a time, selected by curation
rather than searched per task. `recall@k` does not apply to prompts — the metric that matters is
win rate vs. parent, logged per generation, same as skill stats.

### 3.6 Curation

Runs on a schedule (every N generations), not continuously. Applies to both artifact types:

**Skills:**
- Merge near-duplicate signatures.
- Deprecate by usage decay (unused for N generations + low success rate).
- Hard cap on active library size; deprecation is soft (archived, not deleted) for auditability.

**Prompts:**
- Retire a variant that loses to its parent on the regression subset.
- Keep exactly one active version per node; superseded versions are archived, not deleted.
- Merge near-duplicate variants for the same node (embedding or edit-distance threshold).

---

## 4. Evaluation — the actual deliverable

### Task pack

~60 tasks, **40 train / 20 held-out**. Held-out tasks are never seen during evolution.
Domain must be **programmatically checkable**: data wrangling, format conversion, API-shaped
transformations, algorithmic problems with unit tests. No fuzzy grading anywhere in the loop.

### The three curves (on held-out set)

1. **library-off** — baseline, fixed toolset and fixed (hand-written) prompts.
2. **library-on, evolving** — full system, tools and prompts both evolving.
3. **library frozen at generation N, evaluated at N+k** — isolates whether later generations
   improved *because of* the library or independently of it.

Curve 3 is the one that makes the result publishable rather than anecdotal.

### Attribution ablation (tools vs. prompts)

With two evolving artifact types, gains must be attributed correctly, not just claimed for "the
library" as a whole. Required ablation, run at the same generation checkpoints as the three curves
above:

- tools-only evolving, prompts fixed
- prompts-only evolving, tools fixed
- both evolving (this is curve 2 above)

This answers whether gains come from the tool library, the prompt library, or their interaction —
not merely whether the combined system beats baseline.

### Reward-hacking audit

Skills that special-case a specific eval task, and prompts that leak or hard-code eval-specific
phrasing/answers, must be **detected and reported**, not suppressed. A section of the README on
what hacking was found is a feature, not an embarrassment.

### Stretch ablation (Sprint 6, if time)

Re-run the *losing* loop variants from `loop-engineering` with the library attached. Answers
whether a good skill/prompt library closes the gap between control-loop architectures. Both
outcomes are interesting: "tooling dominates loop choice" or "loop choice survives tooling."

---

## 5. Sprint plan

Two weeks each, ~5–8 hrs/week.

| Sprint | Deliverable | Done when |
|---|---|---|
| 1 | Task pack, sandbox runner, skill schema + registry | Baseline agent scored on train + held-out, no library |
| 2 | Generation + admission gate for skills **and** prompts | Skill library and prompt library both grow with provenance; nothing retrieves yet |
| 3 | Retrieval layer (skills) + active-version selection (prompts) + recall@k instrumentation | First end-to-end evolving run, both artifact types live |
| 4 | Curation: dedup, decay deprecation, versioning, size cap — skills and prompts | Both libraries stay bounded across 20+ generations |
| 5 | Eval harness, three curves, tools-vs-prompts attribution ablation, hacking audit, MLflow lineage | The curves and the attribution ablation exist and are reproducible |
| 6 | Hardening, ADRs, README with curves, demo | Someone else can clone and reproduce |

Sprint 1 is shortened relative to a from-scratch build because the tool/task contract is inherited.

**Sprints 1–2 are where projects like this die.** The failure mode is jumping to generation before
a held-out set exists, after which no one can tell whether anything improved. Do not let Sprint 2
start before the held-out split is frozen and committed.

---

## 6. Engineering constraints

- **Sandboxing is non-negotiable.** Generated code executes. Subprocess isolation minimum;
  container preferred. No network by default. Hard timeouts. Resource caps.
- **Prompt mutation candidates don't execute code**, but still consume eval budget (a regression
  run per candidate). Count prompt-variant evals against the same task budget as skill evals so
  the two artifact types stay cost-comparable and neither one dominates by being cheaper to try.
- **Local compute is limited** (6GB VRAM). Assume API-backed models for the agent itself; anything
  requiring local training is out of scope for this project.
- **MLflow 3.0** carries generation lineage — every generation logs skill library state, prompt
  library state, scores, and retrieval metrics as a linked run.
- Determinism where possible: seed everything, pin model versions, log prompts.

---

## 7. Non-goals

- Weight updates or self-training.
- Open-ended or unverifiable task domains.
- Anything requiring `mnemos` to exist.
- Evolving the control-loop *architecture* itself (node graph, routing) — only its tools and its
  per-node prompts are in scope; see the open decision in §2.
