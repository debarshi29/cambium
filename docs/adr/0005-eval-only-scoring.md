# ADR 0005: Node-specific evaluation path for prompt admission

## Status
Accepted.

## Context
While wiring the Sprint 5 eval harness, evaluating a planner `top_k`
mutation through the full loop (`cambium.agent.loop.run_task`, which
includes the generation + reflection fallback) produced a mutation that
never got admitted, even though it measurably improves held-out retrieval.
Root cause: in this repo's scaled demo, the reflector's generation fallback
reliably re-solves a task from scratch (the scripted candidate bank always
has a correct answer one retry away) regardless of whether retrieval found
the right skill. So on the train regression subset, a planner mutation that
fixes a retrieval miss shows *zero* measured improvement — the task was
going to get solved via generation anyway — and CLAUDE.md §3.4 condition 3
("demonstrated reuse... holds across more than one task") correctly refuses
to admit a mutation with no measured gain. The gate did its job on the
number it was given; the number was measuring the wrong thing for this
node.

## Decision
Prompt admission evaluates each node against the part of the loop that
node actually controls, not uniformly through the full loop:

- **planner** mutations are evaluated with `cambium.eval.scoring.score_tasks`
  — retrieval + base capability only, no generation fallback. This isolates
  exactly what `top_k` changes.
- **reflector** and **critic** mutations are evaluated through the full loop
  (`run_task`), since their effect is specifically on the
  generation/reflection/extraction steps that path exercises.

This is a real, permanent difference in how the two node types are judged,
not a special case bolted on to force one particular mutation through. It
generalizes: any prompt node should be evaluated by a code path that can
actually detect what changing that node's prompt is supposed to change.

## Consequences
- `cambium.prompts.admission._evaluate` branches on `node`. Adding a fourth
  prompt node (out of scope per ADR 0001, but worth flagging) would require
  deciding which evaluation path it needs, not assuming the full loop is
  always correct.
- The held-out curves (Sprint 5 eval harness) use the same
  `cambium.eval.scoring` path for a second, independent reason: running
  generation/admission at held-out scoring time would itself violate the
  held-out discipline in ADR 0003. That the same module solves both
  problems is not a coincidence — both are instances of "don't let the
  generation fallback stand in for what's actually being measured."
- This was found empirically (a mutation that should help stubbornly
  wasn't getting admitted), not designed upfront — worth remembering next
  time a gate's "no improvement" result looks surprising: check what the
  evaluation path can actually see before concluding the mutation is bad.
