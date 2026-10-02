# ADR 0013: v1.0 wrap-up: what's production-grade now, what the results support, what's open

## Status
Accepted. Successor to [ADR 0006](0006-sprint-6-wrapup.md), the Sprint 6
scorecard; read that one for the original six sprints.

## What changed since ADR 0006

| ADR 0006 gap | Status in v1.0 |
|---|---|
| Live LLM behind the seam | Done for the loop (0007); **the whole eval harness now runs on the LLM agent** with record/replay cassettes (0012). No live numbers yet (see below). |
| Task pack 20x smaller than spec | **Done**: 60 tasks, 40 train / 20 held-out, 20 categories (0010). |
| Curation never exercised under growth pressure | **Done**: 25-generation stress test (0011), which found and fixed two real curation flaws. |
| Container sandboxing | **Done**: Docker backend, tested in CI (0009); subprocess tier hardened (0008). |
| Stretch ablation on `loop-engineering`'s losing variants | Still blocked: those artifacts aren't available to this repo. |

Production-grade engineering added along the way: persistent,
tamper-checked library snapshots; a `cambium` CLI; structured logging of
admission and curation decisions; a deterministic sandbox verdict cache
(eval 14 s, suite under a minute in CI); mypy and an 88% coverage gate;
a Docker image; CI across Python 3.13/3.14 and both sandbox tiers;
SECURITY/CONTRIBUTING/CHANGELOG.

## Bugs found by making it production-grade
Recorded because they are the strongest evidence that the extra work was
not cosmetic. Each one was found by a new test or check, not by inspection:

- **Two ways to forge a sandbox pass** (0008). Neither was exploited by the
  scripted bank. Both are exactly what an optimizing generator could
  stumble into.
- **Curation deleted a category's only skill, and dedup never fired**
  (0011). Unmeasured curation cost 2 of 20 held-out tasks.
- Re-admission version collision; an empty cache backend treated as "no
  backend"; the CLI leaking `--sandbox` into `os.environ`; a `raise None`
  path in the LLM client.

## What the results support, at spec scale (20 held-out tasks)
- **The attribution ablation**: tools-only 3/20 and prompts-only 3/20 both
  sit exactly on the library-off floor (3/20); only both evolving reaches
  20/20. Prompts-only reaches 40/40 on *train*, so problem-solving ability
  that isn't persisted as an admitted skill doesn't transfer.
- **Curve 3**: frozen at generation 2 scores 19/20 vs. 20/20 live; the
  missing task is a real retrieval collision fixed by an admitted planner
  mutation.
- **Bounded library under pressure**: coverage-aware curation holds 17-24
  active skills across 100 noisy admissions, while the uncurated library
  grows to 117 and its recall@2 decays from 100% to 71%.

## What they still don't support
- **Anything about a real model's behavior.** The reported curves use the
  scripted agent. The live curve needs one recorded run with an API key
  (`cambium eval --agent llm --llm-mode record --llm-cache ...`), which
  this build environment didn't have.
- **Statistical claims.** 20 held-out tasks, one seed, a deterministic
  agent: these are existence results, not effect sizes.
- **Solve-rate damage from ungated growth.** The stress test's noise is
  correct code, so it degrades retrieval but not solving. A proposer that
  emits plausible-but-subtly-wrong variants is the next harsher test.

## Next steps, in priority order
1. Record the live LLM curve, commit the cassette, report it as a separate
   curve next to the scripted one (no infrastructure work left).
2. Multiple seeds / temperatures for the live curve, with intervals.
3. A harsher stress proposer (subtly wrong variants that pass origin but
   not all held-out shapes) to test solve-rate degradation.
4. Embedding-based retrieval as a drop-in behind `RetrievalIndex.query`,
   judged by the same recall@k instrumentation.
5. The stretch ablation, once `loop-engineering` artifacts are available.
