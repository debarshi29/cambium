# ADR 0012: Reproducible live-LLM runs via record/replay, and the LLM curve

## Status
Accepted. Addresses item 1 of [ADR 0006](0006-sprint-6-wrapup.md)'s next
steps ("running the harness itself through the live path, seeded and
repeated, as an explicitly separate fourth curve").

## Context
[ADR 0007](0007-live-llm-integration.md) wired a live Groq model through
the ADR 0002 seam but kept it out of the reported curves, for good reasons:
a live call is not deterministic, costs money, and needs a key, while
CLAUDE.md §6 asks to "seed everything, pin model versions, log prompts."
The live path was therefore only reachable from a per-task smoke test,
never from the evaluation harness. So the project could not say anything
about whether its thesis holds with a real generator in the loop.

## Decision
1. **The harness takes a pluggable agent.** `EvolutionConfig.task_runner`
   (default: the scripted `run_task`) is threaded through `run_evolution`
   and the prompt admission gate's regression runs. The live runner is
   `functools.partial(run_task_llm, client=...)`, which has the same
   signature. `cambium eval --agent llm` runs the full eval (three curves,
   tools-vs-prompts ablation, hacking audit, MLflow lineage) on it and
   writes `eval_report_llm.json` / `library_both_evolving_llm.json`, so the
   scripted results are never overwritten.
2. **Record/replay cassettes** (`cambium.agent.llm_cache.RecordReplayClient`).
   Every exchange is appended to a JSONL cassette keyed by a hash of
   model, temperature, max_tokens, system and user prompt.
   - `record`: always call, always append.
   - `replay`: never call; a prompt not on the cassette raises
     `LLMCacheMiss`. A replay that quietly went live would not be a replay.
   - `auto`: replay hits, record misses (resumable recording).
   The cassette is also the prompt log §6 asks for.

So a live run is done once, with a key (`--llm-mode record --llm-cache
results/llm_cassette.jsonl`), and from then on anyone can reproduce it
exactly, offline and for free (`--llm-mode replay`).

## Verification
Offline, with an "oracle" chat client that answers like a competent model
(a plausible-but-wrong first attempt, the correct code when given sandbox
feedback): the full eval runs end to end through `run_task_llm`, a replay
of the recorded cassette with **no model at all** reproduces the report
exactly, and the same ablation shape appears as with the scripted agent
(tools-only 3/20, prompts-only 3/20, both 20/20). See
`tests/test_llm_cache.py`.

## What this does not yet provide
**No live-model numbers are reported.** The environment this was built in
has no Groq API key, and inventing numbers is not an option (ADR 0002). The
README says so. Producing the LLM curve is now one command for anyone with
a key:

    cambium eval --agent llm --llm-mode record --llm-cache results/llm_cassette.jsonl

and committing the cassette makes it reproducible for everyone else.

## Consequences
- Replay is only as deterministic as the prompts: change a prompt template,
  the task pack, or the generation parameters, and the keys change, so
  replay raises `LLMCacheMiss` instead of serving stale answers. That is
  the intended failure.
- Temperature > 0 makes a *recording* non-deterministic, not a replay:
  re-recording may give a different curve. Report the cassette, not just
  the numbers.
- The sandbox cache stays off by default for live recording (a model's
  code isn't guaranteed to be pure), and on for replay.
