# ADR 0011: Curation stress test, and the two curation flaws it found

## Status
Accepted. Closes the open item in [ADR 0006](0006-sprint-6-wrapup.md):
"the curation stress test ('library size stays bounded across 20+
generations') ... never exercised under real multi-generation growth
pressure end to end."

## Context
The main eval saturates at generation 3 (every category has its skill), so
curation never sees growth pressure there. ADR 0006 named the fix: a
"deliberately noisy generator that keeps proposing near-duplicates over
many generations."

## Decision
`cambium.eval.stress` bootstraps the full 17-skill library (3 generations
of the normal evolution), then runs 25 more generations in which a seeded
**noisy proposer** offers 4 variants per generation: an already-admitted
skill's exact code under a new function name, with its docstring drifted
by 3 words drawn from other tasks' vocabulary -- a generator re-deriving
what it already has and describing it slightly differently each time.

Every variant goes through the unmodified admission gate. They are
correct, so they pass sandbox and reuse; their `(category, fn_name)`
signature is new, so exact-signature dedup lets them in. The gate is not
supposed to stop this -- CLAUDE.md §3.6 assigns it to curation. Each
generation also runs the train set (driving usage stats), curates every
2 generations (cap 24), and records size, deprecations by reason,
held-out score, and recall against the human-labeled canonical skills.
The same seeded proposals run with curation off as the "ungated growth"
arm. `scripts/run_curation_stress.py` writes `results/curation_stress.json`.

## What the first run found
Curation as shipped in Sprint 4 **kept the library bounded but broke it**:

| gen 28, first run | curated (Sprint 4 curation) | uncurated |
|---|---:|---:|
| active skills | 24 | 117 |
| near-duplicate merges | **0** | — |
| held-out solved | **18/20** | 20/20 |

1. **Dedup never fired.** A drifted variant scores ~0.5 Jaccard against
   its original; the threshold was 0.8. All the bounding was done by decay
   and the size cap.
2. **The cap deleted capabilities.** `caesar_cipher_skill` -- the *only*
   caesar skill -- was capped away with a 49% success rate. Its rate was
   low because retrieval kept handing it *other categories'* tasks, so
   success rate was measuring retrieval precision, not the skill. Its
   held-out task then had nothing to retrieve. A second held-out loss came
   from un-merged fibonacci variants crowding `primality_skill` out of the
   top 2.

It also surfaced an admission bug: once curation archived a skill, the
loop re-solved its category and proposed `<category>_skill` as v1 again,
crashing the registry with a version collision.

## Fixes
- **Coverage-aware curation.** Decay never removes a category's last
  active skill. The size cap drops redundant skills (category has another
  active skill) first, lowest value first, and only touches a category's
  last skill if the cap cannot be met otherwise -- the cap stays hard.
- **Same-category dedup threshold** (0.45, alongside the 0.8 cross-category
  one): paraphrases of the same job get merged; unrelated skills that
  happen to share vocabulary across categories do not.
- **Re-admission becomes the next version** (`SkillRegistry.next_version`),
  per CLAUDE.md §3.1's "edits create a new version."

## Results after the fixes (25 generations, 100 proposals)

| generation | curated: active / total versions | curated held-out | curated recall@2 | uncurated: active | uncurated held-out | uncurated recall@2 |
|---:|---:|---:|---:|---:|---:|---:|
| 4 | 17 / 21 | 20/20 | 100% | 21 | 20/20 | 100% |
| 10 | 17 / 45 | 20/20 | 100% | 45 | 20/20 | 88% |
| 16 | 18 / 69 | 20/20 | 100% | 69 | 20/20 | 76% |
| 22 | 19 / 93 | 20/20 | 100% | 93 | 20/20 | 71% |
| 28 | 20 / 117 | 20/20 | 100% | 117 | 20/20 | 71% |

- **Bounded:** active size oscillates between 17 and 24 (a sawtooth: 4
  admissions per generation, a pass every 2) while total versions grows
  monotonically -- everything archived, nothing deleted.
- **Dedup does the work:** 95 near-duplicate merges, 2 decay deprecations,
  0 cap evictions over the run.
- **No capability lost:** all 17 categories covered throughout; held-out is
  20/20 after every pass (it dips to 19/20 in some odd generations, between
  passes, while 4 fresh variants are live).

## What this does and doesn't support
- **Supports** "the library stays bounded across 20+ generations" (§5),
  and the thesis's claim that ungated growth degrades the library:
  uncurated recall@2 decays from 100% to 71% as the library grows 5.5x.
- **Does not show** ungated growth hurting the held-out *solve rate* in
  this scenario: the noise here is correct code, so a mis-retrieved
  variant of the right category still solves the task. Noise that is
  plausible but subtly wrong would; that needs a harsher proposer.
- **Shows curation can do harm.** Before the fixes, curation lost 2
  held-out tasks that no curation would have kept. "Curate the library"
  is not automatically good -- it has to be measured, which is why this
  test now runs in CI.
- recall@1 against *canonical* labels (77% at gen 28, curated) understates
  findability: when dedup keeps a variant over the canonical skill, a
  correct retrieval of that variant counts as a miss.
