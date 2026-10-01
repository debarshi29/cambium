# Low-Level Design

Module-level detail: schemas, method contracts, algorithms, and the exact
thresholds the system runs with. Companion to [HLD.md](HLD.md) (system
view) and the [ADRs](adr/) (rationale). Code is the source of truth if
this drifts from it — every field/method name below is taken directly from
`src/cambium/`, not paraphrased.

---

## 1. Module map

```
src/cambium/
├── tasks/       schema.py, pack.py, data/*.json (60 task files)
├── sandbox/     runner.py (backends, judging), harness_template.py (child),
│                docker_backend.py, cache.py
├── skills/      schema.py, registry.py, admission.py
├── prompts/     schema.py, registry.py, admission.py, defaults.py
├── library/     store.py (persistence)
├── retrieval/   index.py, recall.py, ground_truth.json
├── curation/    curator.py
├── agent/       base_capabilities.py, generation.py, solver.py, loop.py,
│                llm_client.py, llm_generation.py, llm_cache.py
├── eval/        scoring.py, harness.py, hacking_audit.py, lineage.py,
│                stress.py, experiments.py
└── cli.py, __main__.py
```

Dependency direction is strictly downward through this list: e.g.
`eval` imports `agent`/`curation`/`prompts`/`skills`, never the reverse;
`skills` and `prompts` never import `agent` or `eval`. `tasks` and
`sandbox` have no internal dependencies at all. `cli` sits on top of
everything and is imported by nothing.

---

## 2. Data schemas

### 2.1 `tasks.schema.Task` / `TaskCase`

```python
@dataclass(frozen=True)
class TaskCase:
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    expected: Any = None

@dataclass(frozen=True)
class Task:
    id: str
    category: str
    split: str          # "train" | "heldout" — validated in __post_init__
    prompt: str          # natural-language description; retrieval query text
    fn_name: str          # function name the candidate must define
    cases: tuple          # tuple[TaskCase, ...] — non-empty, validated
```

Both frozen: a task is immutable data, loaded once from
`tasks/data/*.json` and never mutated at runtime.

### 2.2 `skills.schema.Skill` / `SkillStats`

```python
@dataclass
class SkillStats:
    invocations: int = 0
    successes: int = 0
    last_used_generation: int | None = None
    # .success_rate property = successes / invocations (0.0 if unused)
    # .record(generation, success) -> new SkillStats (dataclasses.replace)

@dataclass
class Skill:
    name: str
    signature: str
    docstring: str
    source: str                # executable body
    fn_name: str
    tests: tuple                # synthesized TaskCase dicts (origin task's own cases)
    provenance: dict             # {"task_id", "generation", "category"}
    version: int = 1
    deprecated: bool = False
    stats: SkillStats = field(default_factory=SkillStats)
    # .key() -> "name@vN"
    # .retrieval_text() -> f"{name} {category} {docstring}" — never source
```

`stats` mutates via full replacement (`SkillStats.record` returns a new
instance; the registry assigns it back) — the *object* is mutable in
place at the registry layer, but each stats update is otherwise a pure
transform, not an in-place field mutation.

### 2.3 `prompts.schema.Prompt` / `PromptStats`

```python
@dataclass
class PromptStats:
    invocations: int = 0
    wins_vs_parent: int = 0
    losses_vs_parent: int = 0
    last_used_generation: int | None = None

@dataclass
class Prompt:
    name: str
    node: str                    # "planner" | "reflector" | "critic"
    template: str                 # real instruction text + slot=value markers
    docstring: str
    eval_task_ids: tuple           # regression subset this variant was measured on
    provenance: dict                # {"parent": "<key>" | None, "generation": int}
    version: int = 1
    deprecated: bool = False
    stats: PromptStats = field(default_factory=PromptStats)
    # .key() -> "node:name@vN"
    # .params() -> {slot: int} parsed from template via regex \b(\w+)=(\d+)\b
    # .retrieval_text() -> f"{node} {name} {docstring}"
```

**`params()` is the load-bearing mechanism that makes prompt mutation
real rather than cosmetic**: the loop reads `planner.params()["top_k"]`,
`reflector.params()["max_attempts"]`, `critic.params()` — editing the
template text is what changes runtime behavior, not a side-channel config
object the template merely narrates. See `prompts/schema.py`'s docstring.

---

## 3. `tasks` — pack loading

`load_task_pack(data_dir=DEFAULT_DATA_DIR)` reads every `*.json` in
`tasks/data/`, sorted by filename (deterministic load order), constructs
one `Task` per file, and wraps them in `TaskPack(tasks=tuple(...))`.
`TaskPack.__post_init__` rejects duplicate ids.

Key methods:

| Method | Contract |
|---|---|
| `.train` / `.heldout` | list comprehension filtered by `split` |
| `.by_id(task_id)` | linear scan, raises `KeyError` if absent |
| `.by_category(category, exclude_id=None, split=None)` | filtered list |
| `.other_task_in_category(task, split=None)` | first match from `by_category`, or `None` |

`other_task_in_category(..., split="train")` is the exact call the
admission gate's reuse check (§5) makes — **never** called with
`split="heldout"` or `split=None` anywhere admission-adjacent; that
invariant is what keeps held-out data out of every admission decision
([ADR 0003](adr/0003-scaled-demo.md)).

---

## 4. `sandbox` — isolated execution

`run_in_sandbox(source, fn_name, cases, timeout=None, limits=None, backend=None) -> SandboxResult`

```python
@dataclass(frozen=True)
class SandboxLimits:
    timeout: float = 5.0
    memory_mb: int = 512
    max_output_bytes: int = 64 * 1024

@dataclass
class SandboxResult:
    ok: bool
    reason: str  # ok | assertion_failed | exception | timeout | violation | resource_limit
    stdout: str
    stderr: str
    returncode: int
```

`backend` defaults to the process-wide one: `CAMBIUM_SANDBOX=subprocess`
(default) or `docker`, optionally wrapped in a `CachingBackend`
(`CAMBIUM_SANDBOX_CACHE=1`). An unknown or unusable backend raises
`SandboxBackendError`. The default is chosen with `is None`, never `or`,
because an empty cache defines `__len__` and is falsy.

Algorithm (identical for both tiers, see `write_sandbox_dir` / `judge`):
1. Fresh scratch dir containing `candidate.py` (the source),
   `harness.py` (a copy of `harness_template.py`) and `cases.json`
   (**call arguments only**, never expected values).
2. Child: `python -I -S harness.py <limits-json>`, `env={}`, cwd = scratch
   dir. Subprocess tier: a local child process. Docker tier: `docker run
   --rm --network none --read-only --tmpfs /tmp --cap-drop ALL
   --security-opt no-new-privileges --user 65534:65534 --memory/--memory-swap
   --cpus 1 --pids-limit 64 -v <scratch>:/sandbox`.
3. In the child, before any candidate code: read inputs; apply rlimits
   (`RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_FSIZE`; POSIX); arm a `SIGALRM`
   wall-clock timer (POSIX); install the audit hook. The hook refuses
   events with prefixes `socket.`, `subprocess.`, `os.system`, `os.exec`,
   `os.spawn`, `os.posix_spawn`, `os.fork`, `os.kill`, `ctypes.`, ... and
   `import ctypes`, and refuses filesystem mutation (`open` for writing,
   `os.remove`, `os.rename`, `shutil.rmtree`, ...) outside the scratch dir.
4. `exec` the candidate, call `fn_name` per case, write each return value
   (JSON round-tripped; non-serializable → error) to `result.json`.
5. Parent (`judge`): no result file → `resource_limit` if killed by a
   limit signal (negative code, or `128+N` from a container), else
   `exception`. Child-reported error → `violation` / `timeout` /
   `resource_limit` / `exception`. Otherwise compare each value with
   `values_equal` (strict structural equality over JSON; `True != 1`) →
   first mismatch is `assertion_failed` with an
   `AssertionError: case i failed: args=... expected=... got=...` line.
6. stdout/stderr read back capped at `max_output_bytes`.

`CachingBackend(inner, maxsize=8192)`: LRU keyed by sha256 of (source,
fn_name, full cases, limits); caches only `ok`, `assertion_failed`,
`exception`, `violation`.

This is the **one and only** execution path for untrusted code in the
whole system: the admission gate, the training loop, and the eval-only
scorer all route through it.

---

## 5. `skills` — registry and admission

### 5.1 `SkillRegistry`

In-memory, keyed `name -> list[Skill]` (all versions kept). `.add()`
raises on a version collision. `.active()` returns one entry per name —
the highest-version non-deprecated `Skill` — so multiple versions can
coexist in history while exactly one (or zero) is "live" per name.
`.has_equivalent(category, fn_name)` is the dedup lookup: same
`(category, fn_name)` pair among active skills counts as the same job.
`.deprecate(name, version, reason="")` flips `deprecated=True` in place —
**never removes**. `.clone()` is `copy.deepcopy`, used by prompt
admission to trial-run a candidate without polluting the registry
actually driving production curves.

`next_version(name)`, `all_skills()` (full history, stable order),
`to_dict()` / `from_dict()`. `deprecate(name, version, reason)` stores the
reason on the skill (`deprecation_reason`).

### 5.2 `admit_skill(candidate, registry, task_pack) -> AdmissionResult`

```python
@dataclass
class AdmissionResult:
    admitted: bool
    reason: str   # "admitted" | "sandbox_failed" | "duplicate" | "no_reuse_task" | "reuse_failed"
    detail: str = ""
```

Four conditions, checked in order, first failure short-circuits:

1. **Sandbox + synthesized tests** (CLAUDE.md §3.2 conditions 1+2
   collapse into one check here): `run_in_sandbox(candidate.source,
   candidate.fn_name, candidate.tests)` — `tests` *is* the origin task's
   own cases, so this single sandbox run covers both "executes without
   error" and "synthesized tests pass."
2. **Dedup** (condition 3): `registry.has_equivalent(category, fn_name)`
   — if a non-deprecated skill already covers this signature, reject as
   `"duplicate"`.
3. **Reuse task lookup**: `task_pack.other_task_in_category(origin_task,
   split="train")` — `None` → `"no_reuse_task"`.
4. **Demonstrated reuse** (condition 4): run the candidate in the sandbox
   against the *second* task's cases. Fail → `"reuse_failed"` (this is
   the exact rejection path the reward-hacking audit reports on — see
   §9). Pass → `registry.add(candidate)`, return `"admitted"`.

---

## 6. `prompts` — registry and admission

### 6.1 `PromptRegistry`

Keyed `node -> list[Prompt]`. `.active(node)` returns the highest-version
non-deprecated `Prompt` for that node — **must always return exactly
one**; `KeyError` if none (the loop cannot run without an active prompt
per node, unlike skills where zero active is a normal state).
`.all_versions(node)`, `.deprecate(node, version)`, `.clone()` (deep
copy) parallel the skill registry.

`prompts.defaults.seed_default_registry()` builds the `library-off`
baseline: `copy.deepcopy` of each of `PLANNER_V1`/`REFLECTOR_V1`/
`CRITIC_V1` per call — a documented, previously-real bug (§10) was
inserting the *same* module-level `Prompt` objects into every registry,
so mutating one registry's prompt silently mutated all of them.

### 6.2 `admit_prompt(candidate, parent, other_nodes, regression_task_ids, task_pack, prompt_registry, base_skill_registry, generation, regression_tolerance=0, min_gained_tasks=2) -> PromptAdmissionResult`

```python
@dataclass
class PromptAdmissionResult:
    admitted: bool
    reason: str   # "admitted" | "no_improvement" | "regression" | "reuse_not_demonstrated" | "duplicate"
    candidate_rate: float = 0.0
    parent_rate: float = 0.0
    gained_task_ids: tuple = ()
    regressed_task_ids: tuple = ()
```

1. **Dedup** (condition 4, checked first): any existing non-deprecated
   variant for this node with identical `.params()` → `"duplicate"`.
2. **Evaluate both** candidate and parent on `regression_task_ids`, via
   `_evaluate()` — see §6.3 for why this branches by node — against a
   **cloned** skill registry (trial runs never touch production state).
3. `gained = candidate_solved - parent_solved`, `regressed = parent_solved - candidate_solved`
   (set difference over task ids).
4. **Condition 2**: `len(regressed) > regression_tolerance` (default
   `0` — zero tolerance for any regression) → `"regression"`. Else
   `candidate_rate < parent_rate` → `"no_improvement"`.
5. **Condition 3** (demonstrated reuse): `len(gained) == 0` →
   `"no_improvement"`; `len(gained) < min_gained_tasks` (default `2`) →
   `"reuse_not_demonstrated"` — a variant that only helps one task is
   rejected, the prompt analogue of the skill gate's reuse check.
6. Otherwise `prompt_registry.add(candidate)`, `"admitted"`.

### 6.3 `_evaluate()` — the node-specific branch

```python
if node == "planner":
    return score_tasks(regression_task_ids, registry, prompt, task_pack)   # eval.scoring — no generation
else:  # reflector, critic
    # full run_task loop, this node's candidate substituted in,
    # other two nodes held at whatever `other_nodes` passes
```

Planner candidates are scored through `eval.scoring.score_tasks` — the
narrower retrieval+base-capability path — instead of the full loop.
[ADR 0005](adr/0005-eval-only-scoring.md) is the full rationale: judging a
retrieval-only prompt through a loop with a generation fallback hides
retrieval failures behind fresh-generation success, so a planner mutation
that only fixes retrieval never looks like an improvement and can never
clear condition 2. This was a real bug, caught by inspecting why an
obviously-correct `top_k` fix kept getting rejected.

---

## 7. `retrieval` — index and recall@k

### 7.1 `RetrievalIndex.query(task, top_k) -> list[ScoredSkill]`

```python
def tokenize(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}
    # _WORD_RE = r"[a-z0-9]+"; ~20 stopwords (a, an, the, of, to, and, ...)
```

Scoring: for each active skill, `overlap = len(tokenize(task.prompt) &
tokenize(skill.retrieval_text()))`; keep if `overlap > 0`. Sort by
`(-score, skill.name)` — highest overlap first, ties broken
alphabetically for determinism. Return the top `top_k`.
`retrieval_text()` is docstring + name + category — **never source** —
so this measures description quality, not grepping the implementation.
`tokenize` is exported and reused by `curation.dedup_skills` (§8.1), so
"what words does this text contain" has one definition system-wide.

### 7.2 `measure_recall_at_k(skill_registry, task_pack, k, generation, ground_truth=None) -> RecallReport`

```python
@dataclass
class RecallReport:
    k: int
    generation: int
    total: int        # tasks whose ground-truth skill is *currently admitted*
    hits: int
    misses: tuple
    # .recall_at_k property = hits / total (0.0 if total == 0)
```

For each `(task_id, expected_skill_name)` in the hand-labeled
`ground_truth.json`: skip if `expected_skill_name` isn't currently an
active skill (denominator measures *findability of what exists*, not
admission coverage — that's curation's job). Otherwise query the index
at `k` and check membership. This is a metric **about** the index,
deliberately not folded into task success — a task can be solved via
base capability even when retrieval completely misses.

---

## 8. `curation` — dedup, decay, cap, archive

Constants: `DEDUP_SIMILARITY=0.8`, `SAME_CATEGORY_DEDUP_SIMILARITY=0.45`,
`UNUSED_FOR_N_GENERATIONS=5`, `MIN_SUCCESS_RATE=0.5`,
`MAX_ACTIVE_SKILLS=20`.

A **sole cover** is an active skill that is the only active skill of its
category. Decay never removes one; the cap removes one only as a last
resort ([ADR 0011](adr/0011-curation-stress-test.md)).

### 8.1 `dedup_skills(registry, threshold=0.8, same_category_threshold=0.45) -> [(kept, dropped)]`

All-pairs comparison over `registry.active()` (sorted by name for
deterministic iteration): Jaccard similarity of `tokenize(retrieval_text())`
sets. Pairs in the same category use `same_category_threshold`, others
`threshold`. Merged pairs keep the higher `(success_rate, invocations,
name)` and deprecate the other with `reason="near-duplicate"`. A skill
already dropped in this pass is skipped for the rest of it.

### 8.2 `decay_deprecate_skills(registry, current_generation, unused_for_n_generations=5, min_success_rate=0.5) -> [name]`

A skill that is not a sole cover is deprecated iff **both**:
- **stale**: never used and the library predates the window
  (`last_used_generation is None and current_generation >
  unused_for_n_generations`), or last used more than the window ago;
- **weak**: zero invocations, or `success_rate < min_success_rate`.

### 8.3 `cap_skill_library(registry, max_active=20) -> [name]`

While `len(registry) > max_active`: among the non-sole-cover skills (or all
skills, if every remaining skill is a sole cover), deprecate the minimum by
`(success_rate, invocations, last_used_generation or -1)` with
`reason="size cap"`. The cap stays hard.

### 8.4 `archive_superseded_prompts(registry) -> [(node, version)]`

For each of the three fixed nodes: every non-deprecated version below
that node's current max version gets explicitly deprecated. Enforces
"exactly one active version per node" as a real, auditable state rather
than an implicit property of `.active()` always picking the max.

### 8.5 `dedup_prompts(registry) -> [(node, kept_version, dropped_version)]`

Safety net beyond the admission gate's own dedup check: groups live
variants per node by `tuple(sorted(v.params().items()))`; within any
group of size ≥2, keeps the one with the best `(wins_vs_parent, version)`,
archives the rest.

### 8.6 `run_curation(...)  -> CurationReport`

Runs all five passes above in order (dedup skills → decay → cap →
archive prompts → dedup prompts) and returns a report with every action
taken. Called by the eval harness every `curation_every` generations
(default 2), not continuously — CLAUDE.md §3.6.

---

## 9. `eval` — scoring, harness, audit, lineage

### 9.1 `eval.scoring.score_tasks(task_ids, skill_registry, planner, task_pack) -> {task_id: bool}`

`retrieval_or_base_solved(task, registry, planner)`: query the index at
`planner.params()["top_k"]`, sandbox each candidate skill in ranked
order, return `True` on first pass; else try base capability; else
`False`. **No generation fallback anywhere in this path** — that's the
entire reason it exists as a separate function from `run_task` (§9.2
uses it for two distinct purposes, see ADR 0005).

### 9.2 `eval.harness.run_evolution(task_pack, config, label="run") -> EvolutionResult`

```python
@dataclass
class EvolutionConfig:
    generations: int = 4
    evolve_skills: bool = True
    evolve_prompts: bool = True
    curation_every: int = 2
    mutation_schedule: dict = ...   # {2: ("reflector", 2, REGRESSION_SUBSET), 3: ("planner", 2, ())}
    planner_regression_task_ids: tuple = ()   # () means "all train tasks"
```

Per generation `gen` in `1..config.generations`:
1. If `evolve_prompts` and `gen` is in the mutation schedule: build a
   scripted candidate `Prompt` for that node (`_mutation_template`
   produces literal `max_attempts=N` / `top_k=N` text), call
   `admit_prompt`, log the result.
2. Pull each node's current active prompt.
3. For every **train** task, call `run_task(..., persist_skills=
   config.evolve_skills)` — the `evolve_skills=False` flag is the
   tools-fixed ablation arm: the loop still runs generation, just never
   calls `admit_skill`. Log every admission attempt.
4. If `gen % curation_every == 0`, run curation.
5. Score **held-out** via `score_tasks` (never `run_task`) against the
   *current* planner and skill registry state.
6. Measure `recall@1` and `recall@top_k`.
7. Append a `GenerationRecord`, snapshotting both registries via
   `.clone()` — so later curve computation can reconstruct any past
   generation's exact library state.

`score_frozen_snapshot(record, task_pack)` implements curve 3: re-scores
held-out using a *stored* `GenerationRecord`'s registries — since
`score_tasks` is a pure function of registry state, "frozen at N,
evaluated at N+k" is the same number for every k; the interesting
comparison is this flat value against curve 2's live trajectory from N
onward.

The four ablation arms (library-off, tools-only, prompts-only, both) are
four separate `run_evolution` calls with different
`EvolutionConfig.evolve_skills` / `evolve_prompts` combinations — not a
single run branching internally.

### 9.3 `eval.hacking_audit`

Two independent, differently-scoped checks, deliberately not merged into
one:

- `audit_admission_log(admission_log)` — every `AdmissionResult` with
  `reason == "reuse_failed"` is by construction a candidate that solved
  its origin task but failed to generalize; reported as a finding, not
  hidden for reflecting well on the gate.
- `audit_admitted_skills(registry)` — an independent AST scan
  (`_looks_like_literal_lookup`) over every *currently admitted* skill's
  source, flagging (a) a `dict` literal with ≥2 constant keys as the sole
  return path, or (b) an `if`/`elif` chain of ≥2 branches each comparing
  to a literal constant. Catches a hack that might slip past the reuse
  check by coincidence (the reuse task's expected values happening to
  match the hardcoded ones) — finding nothing here is one more check, not
  proof of nothing wrong.

### 9.4 `eval.lineage` (MLflow)

`configure()` sets `sqlite:///mlruns.db` as the tracking URI (the
filesystem backend is deprecated in MLflow 3.x) and the
`cambium-evolution` experiment. `evolution_run(name, params)` is a
context manager opening one parent run; `generation_run(gen)` opens one
**nested** child run per generation inside it. `log_generation_metrics`
logs train/held-out rate, active skill count, and recall figures with
`step=generation`. `log_library_snapshot` dumps active skills (with
provenance + stats) and each node's active prompt version/params as a
JSON artifact per generation — the literal "library state" lineage
CLAUDE.md §6 asks for.

---

## 9.5 `eval.stress`, `eval.experiments`, `library.store`, `agent.llm_cache`, `cli`

- `run_stress(task_pack, StressConfig) -> StressResult`: bootstrap 3
  generations, then `generations` rounds of: propose
  `variants_per_generation` variants (same code, `fn_v{gen}_{i}`, docstring
  + `drift_words` sampled words, seeded) through `admit_skill`; run train;
  curate every `curation_every`; record size, versions, deprecations,
  held-out, recall@1/@k.
- `run_full_eval(pack, generations, freeze_at, task_runner=None) -> EvalOutcome`;
  `run_baseline(pack)`; `log_lineage(outcome, pack, tracking_uri, run_name, extra_params)`.
- `save_library(path, skills, prompts, generation, metadata)` /
  `load_library(path) -> LibrarySnapshot`: `schema_version=1`, atomic
  write (temp + `os.replace`), skill `fingerprint` (sha256 of source,
  16 hex) verified on load.
- `RecordReplayClient(cassette, mode, inner)`: key = sha256(model,
  temperature, max_tokens, system, user); JSONL append; `replay` raises
  `LLMCacheMiss` on unknown prompts.
- `cambium.cli.main(argv) -> int`: exit 0 ok, 2 for known failures
  (sandbox, library, args, LLM config), 1 for `library diff --exit-code`
  differences, 130 on Ctrl-C.

---

## 10. Known bugs found and fixed (transparency, not erasure)

Each is documented at its fix site, not just here:

| Bug | Where | Root cause | Fix |
|---|---|---|---|
| Sandbox harness indentation corruption | `sandbox/runner.py` | `textwrap.dedent()` over an f-string containing arbitrary candidate indentation used the *combined* text's common whitespace | Plain concatenation + `.replace()` templating |
| Shared singleton prompts across registries | `prompts/defaults.py` | Module-level `Prompt` constants inserted by reference into every registry `seed_default_registry()` built | `copy.deepcopy` per call |
| Planner mutation never admitted | `prompts/admission.py` | Full-loop evaluation let the reflector's generation fallback mask retrieval-only improvements | Node-specific `_evaluate()`, planner → `eval.scoring.score_tasks` ([ADR 0005](adr/0005-eval-only-scoring.md)) |
| Missing planner entry in `MUTATION_SCHEDULE` | `eval/harness.py` | Simple omission | Added `3: ("planner", 2, ())`, caught by empty `admission_log` inspection |
| Task pack missing train-only reuse partners | `tasks/data/*.json` | Initial 20-task pack had 4/7 skill categories with only a train+heldout pair | Restructured to 27 tasks, every skill category gets 2 train + 1 heldout |
| Forgeable sandbox pass (printed OK marker; always-equal return object) | `sandbox/runner.py` | Parent trusted a stdout marker; comparison ran in the child with `!=` | Child gets args only; parent judges JSON values strictly ([ADR 0008](adr/0008-sandbox-hardening.md)) |
| Empty cache backend silently ignored | `sandbox/runner.py` | `backend or default` with a backend defining `__len__` | `if backend is None` |
| Curation deleted a category's only skill; dedup never fired | `curation/curator.py` | Success rate penalized retrieval mistakes; 0.8 threshold vs ~0.5 for paraphrases | Coverage-aware decay/cap; same-category threshold ([ADR 0011](adr/0011-curation-stress-test.md)) |
| Version collision on re-admission | `skills/admission.py` | Re-solved category re-proposed `<cat>_skill@v1` after curation archived v1 | Lands as `next_version` |
| CLI `--sandbox` leaked into later calls | `cli.py` | Mutated `os.environ` | `backend_from_env(choice)` |
| `GroqClient.chat` could `raise None` | `agent/llm_client.py` | Negative `retries` skipped the loop | Explicit error (found by mypy) |

---

## 11. Test coverage map

| Module | Test file |
|---|---|
| `sandbox.runner` | `test_sandbox.py` (incl. forgery, isolation, limits) |
| `sandbox.docker_backend`, backend selection | `test_sandbox_backends.py` (docker tests run in CI's docker job) |
| `sandbox.cache` | `test_sandbox_cache.py` |
| `tasks.pack` / `schema` | `test_task_pack.py` |
| `skills.registry` | `test_skills_registry.py` |
| `library.store` | `test_library_store.py` |
| `agent.base_capabilities` | `test_base_solver.py` |
| `agent.generation` | `test_generation.py` |
| `skills.admission` | `test_skill_admission.py` |
| `agent.loop` (`run_task`) | `test_loop.py` |
| `prompts.admission` | `test_prompt_admission.py` |
| `retrieval.recall` | `test_recall.py` |
| `prompts.registry` | `test_prompt_registry.py` |
| `curation.curator` | `test_curation.py` |
| `eval.stress` | `test_curation_stress.py` |
| `eval.scoring` | `test_eval_scoring.py` |
| `eval.hacking_audit` | `test_hacking_audit.py` |
| `eval.harness` | `test_eval_harness.py` |
| `eval.lineage` | `test_lineage.py` (throwaway sqlite store) |
| `cli`, `eval.experiments` | `test_cli.py` |
| `agent.llm_client` | `test_llm_client.py` (mocked `requests.post`, no network) |
| `agent.llm_generation` | `test_llm_generation.py` (fake client) |
| `agent.loop` (`run_task_llm`) | `test_llm_loop.py` (scripted fake client) |
| `agent.llm_cache`, harness on the LLM agent | `test_llm_cache.py` (offline oracle client) |

~160 tests, zero network calls, zero API keys required. CI runs them on
Python 3.13 and 3.14 with an 88% coverage gate, plus the sandbox suite
against the Docker tier.
