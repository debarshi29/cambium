# ADR 0007: Live LLM integration via Groq, kept separate from the eval curves

## Status
Accepted.

## Context
`docs/adr/0002-agent-stand-in.md` named "wire an actual model behind the
`Solver.attempt` seam" as the natural next step, outside that session's
scope. A Groq API key became available. This ADR records what got wired in,
and — as important — what deliberately did *not* change as a result.

## Decision
Added a live path alongside the scripted stand-in, not in place of it:

- `cambium.agent.llm_client.GroqClient` — a thin OpenAI-compatible chat
  wrapper (`requests`, one retry, reads `GROQ_API_KEY` from `.env` via
  `python-dotenv`). `.env` is gitignored; `.env.example` documents the shape.
- `cambium.agent.llm_generation` — builds the codegen/reflection/critic
  prompts and parses code back out of a reply. `llm_generate` is the
  `planner`+`reflector` content: a fresh generation prompt on the first
  attempt, a retry-with-sandbox-error prompt on subsequent attempts within
  the reflector's `max_attempts` budget. `llm_critic_is_general` is the
  `critic` content: the model is asked whether a passing candidate looks
  hardcoded to its example values before the loop bothers proposing it to
  the admission gate — advisory only, since the gate's reuse check (running
  the candidate against a second task) is what actually decides admission.
- `cambium.agent.loop.run_task_llm` — the identical node sequence and
  identical retrieval/base-capability/admission-gate mechanics as
  `run_task`, with the generation fallback and critic decision routed
  through the two functions above instead of the scripted `CANDIDATE_BANK`
  and `min_lines` heuristic. Retrieval, base capabilities, and the
  admission gate itself are untouched.
- `scripts/run_llm_demo.py` — runs one train task per skill-requiring
  category through `run_task_llm` against the real API and prints the
  outcome. Verified working end to end at the time of writing: 10/10 tasks
  solved (3 via base capability, 7 via live generation), all 7 live-
  generated skills passed the admission gate's reuse check on a second,
  different task.
- Model: `openai/gpt-oss-20b`. (`llama-3.1-8b-instant`, the model this was
  originally scoped for, is no longer in Groq's model catalog as of this
  writing — confirmed via `GET /openai/v1/models` before picking a
  replacement. `gpt-oss-20b` is the closest available analog: a fast,
  smaller open-weights model.)

## What deliberately did not change
- **The README's three curves and attribution ablation are still the
  scripted path (`run_task`, `cambium.agent.generation`), not this one.**
  CLAUDE.md §6 requires determinism ("seed everything, pin model versions,
  log prompts"); a live model call is neither deterministic nor free
  (real API cost per call, real latency, real output variance run to run).
  Re-running the eval harness through `run_task_llm` would produce numbers
  that can't be reproduced by a reader without their own API key and would
  drift between runs — not what those curves are for. If a live-LLM eval
  curve is wanted later, it belongs alongside the existing ones as a fourth
  curve with its own variance reported (e.g. mean ± range over N seeded
  runs), not as a silent replacement.
- **Admission, retrieval, and curation code — zero changes.** This is the
  ADR 0002 seam working exactly as advertised: a new solver/generator
  slotted in without touching the gate, the index, or the curator.
- **The 68 pre-existing tests are untouched and still pass**, alongside 14
  new tests for the live path, all against a scripted fake client (no
  network, no API key needed) — see `tests/test_llm_client.py`,
  `tests/test_llm_generation.py`, `tests/test_llm_loop.py`.

## Consequences
- ADR 0002's gap is now partially closed: a real model can solve real tasks
  through the real loop, and that has been demonstrated once, live, not
  just claimed as a possibility. It is not yet closed for the *evaluation*
  story — the headline numbers in the README are still about the harness
  operating on the scripted stand-in, and must keep saying so.
- Anyone reproducing `scripts/run_llm_demo.py` needs their own
  `GROQ_API_KEY`; anyone running `python -m pytest` or
  `scripts/demo.py` does not — those stay fully self-contained.
- Next actual step toward closing ADR 0002 for real: run the eval harness
  itself through `run_task_llm`, seeded and repeated, and report it as an
  explicitly separate, higher-variance fourth curve rather than touching
  curves 1–3.
