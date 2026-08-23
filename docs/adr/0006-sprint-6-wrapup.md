# ADR 0006: Sprint 6 wrap-up — what shipped, what didn't, what's next

## Status
Accepted.

## Context
CLAUDE.md §5 defines Sprint 6 as done when "someone else can clone and
reproduce." This ADR records the state at that point, honestly, rather than
letting the README imply more than what's here.

## What shipped
All six sprints, against the scaled-down demo described in
`docs/adr/0003-scaled-demo.md`:

- 27-task pack (18 train / 9 held-out), sandboxed runner, skill + prompt
  schemas and registries.
- Admission gates for both artifact types, with a real rejection exhibit
  (the overfit `run_length_encoding` candidate) and a real acceptance
  exhibit for each.
- Retrieval with recall@k instrumentation, including a genuine (not staged)
  retrieval collision found while testing.
- Curation: dedup, decay deprecation, size cap, version archiving — plus a
  real cross-registry state-leak bug found and fixed while testing it
  (`docs/adr` reference: see the Sprint 4 PR / commit message; the fix
  itself lives in `cambium.prompts.defaults`).
- The three curves and the tools-vs-prompts attribution ablation, executed
  for real: library-off 2/9, library-on-evolving 9/9, frozen-at-2 8/9,
  tools-only 2/9, prompts-only 2/9 (despite 18/18 train). See
  `results/eval_report.json` and the README results table.
- Reward-hacking audit wired into the eval run, not a separate manual step.
- MLflow lineage via mlflow-skinny against a local sqlite store.

## What didn't ship (by design, not oversight)
- **No live LLM.** The agent, and skill/prompt candidate generation, are
  scripted stand-ins (`docs/adr/0002`). Every number in this repo is a
  measurement of the harness operating on that stand-in, not of an LLM's
  code-generation or self-improvement ability. Swapping in a real model
  behind `Solver.attempt` is the natural next step and does not require
  touching admission, retrieval, curation, or eval code.
- **20x smaller task pack than spec** (27 vs. ~60) — `docs/adr/0003`.
  Percentages in this repo should be read as "N of 27," not as statistically
  powered results.
- **Subprocess isolation, not container isolation** — `docs/adr/0004`.
- **Scripted prompt mutation proposals at two fixed generation
  checkpoints**, not an open-ended search — see `cambium.eval.harness`.
  This was a deliberate scope cut to keep the demo run interpretable enough
  to hand-verify every number in it, which is how the eval-only-scoring bug
  in `docs/adr/0005` got caught in the first place.

## What the results do and don't support
**Supports the thesis**, at this scale: the tools-only and prompts-only
ablations *each independently* land exactly at the library-off floor;
only both together reach the ceiling. That is a real interaction effect
produced by the actual gate/generation/eval mechanics, not curve-fit
afterward — the numbers were run, read, and reported as they came out,
including the parts (Sprint 4's registry bug, Sprint 5's eval-only-scoring
bug) that weren't flattering on first run.

**Does not yet support**: the curation stress test ("library size stays
bounded across 20+ generations" per CLAUDE.md §5's Sprint 4 done-when) —
this demo runs 4 generations, past which the task pack is already fully
solved and there is nothing left to evolve toward. Curation's mechanisms
are unit-tested (`tests/test_curation.py`) but never exercised under real
multi-generation growth pressure end to end. That needs either a much
larger task pack or a deliberately noisy generator that keeps proposing
near-duplicates over many generations — noted here rather than silently
left for someone to discover the gap.

## Next steps, in priority order
1. ~~Real LLM behind `Solver.attempt` (ADR 0002's seam)~~ — **done for the
   agent loop itself**, see `docs/adr/0007-live-llm-integration.md`: a live
   Groq-backed path now solves real tasks through the real admission gate,
   with zero changes to admission/retrieval/curation code. **Not yet done**
   for the eval curves — those still run the scripted stand-in on purpose
   (determinism, cost, reproducibility; ADR 0007's rationale). Running the
   harness itself through the live path, seeded and repeated, as an
   explicitly separate fourth curve is the next real step here.
2. Task pack to spec size (60 tasks) — mechanical, not architectural.
3. A curation stress scenario: either the larger pack or a synthetic noisy
   generator, run for 20+ generations, to actually test the "library stays
   bounded" claim rather than assume the unit tests cover it.
4. Container sandboxing tier (ADR 0004).
5. The stretch ablation from CLAUDE.md §4 (re-run losing `loop-engineering`
   variants with the library attached) — blocked on `loop-engineering`
   artifacts being available in this environment, not on anything in this
   repo.
