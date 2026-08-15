# ADR 0002: Deterministic scripted stand-in for the LLM-backed agent

## Status
Accepted.

## Context
CLAUDE.md §6 assumes an API-backed model as the agent. This repo, built in a
single working session with no LLM API credentials configured in the
execution environment, cannot make real per-task LLM calls for "act",
"reflect", or "generate a skill/prompt candidate". Two options existed:
fabricate plausible-looking results as if a real LLM had produced them, or
build the harness against a transparent, documented, non-LLM stand-in and
report genuine numbers *for that stand-in*. The first option is not
available — it would mean reporting fabricated evidence as a real finding
about library-gated evolution, which is precisely the kind of unverified
claim CLAUDE.md's thesis (§1) exists to guard against making.

## Decision
`cambium.agent.solver.Solver` is the seam. `BaseSolver` (library-off) and
`LibrarySolver` (library-on, added in Sprint 2+) implement it as
**deterministic, scripted logic** — a fixed lookup from task category to
known-correct source code, gated by whether a skill/base-capability exists
for that category — standing in for what would ordinarily be an LLM call.
Skill and prompt *candidate generation* (`cambium.agent.generation`) is
equally scripted: a fixed oracle bank keyed by category, including one
deliberately overfit candidate (see the reward-hacking audit in the Sprint 5
eval report) to exercise the admission gate's reuse condition against a
candidate that should be rejected, not just candidates that should pass.

## Consequences
- **What this repo's results do and do not show.** The three curves and the
  attribution ablation in this repo are genuine, executed measurements of
  the *harness* — admission gates, retrieval, curation, curve/ablation
  computation — operating on a real (if scripted) generation process. They
  are not evidence about LLM code-generation quality, and the README must
  not imply otherwise.
- **The swap-in point is real, not aspirational.** Any object implementing
  `Solver.attempt(task) -> AttemptResult` and a matching candidate-generation
  function can replace the scripted versions without touching admission,
  retrieval, curation, or eval code. Wiring an actual Claude API call
  through this interface is the natural next step outside this session's
  scope, not a redesign.
- Every module that depends on this stand-in (`agent/solver.py`,
  `agent/generation.py`) carries a docstring pointing back to this ADR, so
  the limitation surfaces at the point someone would be tempted to trust the
  numbers as more than they are.
