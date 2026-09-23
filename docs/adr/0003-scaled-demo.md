# ADR 0003: Scaled-down task pack for this session's run

## Status
Superseded in scale by [ADR 0010](0010-full-task-pack.md) (60 tasks); the
discipline rules below still apply.

## Context
CLAUDE.md §4 specifies ~60 tasks, 40 train / 20 held-out. Producing that at
real scale means 60 hand-written, individually-verified programmatically-
checkable tasks plus enough per-category duplication for the reuse condition
in both admission gates — a multi-session effort on its own, independent of
the agent stand-in question (ADR 0002).

## Decision
This session ships a 27-task pack (18 train / 9 held-out — the same 2:1
ratio as the full spec) across 10 categories. The 7 categories that require
a synthesized skill (everything except the 3 base-capability categories
below) get **3 tasks each: 2 train + 1 held-out** — not 2 total — because
the admission gate's reuse check (CLAUDE.md §3.2 condition 4) must never
touch held-out tasks (see docs/adr/0004 on discipline boundaries; enforced
by `test_skill_categories_have_two_train_tasks_for_admission_reuse_check`).
Two train tasks per category give the origin task and an in-train reuse
target; the held-out task exists purely to measure whether an admitted
skill generalizes, never to admit it. The 3 base-capability categories
(`string_reverse`, `word_count`, `palindrome_check`) don't go through
admission at all, so they keep 2 tasks each. Those three categories are
solvable by the agent's base capabilities with no library at all, by
design — this is what makes the library-off baseline non-trivial
(CLAUDE.md §4 curve 1) instead of scoring zero, and what makes any measured
lift from the library attributable to the library rather than to the floor
being zero.

## Consequences
- Curves and the attribution ablation in this repo are real but small-n —
  read percentages as "N of 20", not as statistically powered results.
  Sprint 5's eval report states the pack size next to every curve for this
  reason.
- The task schema (`cambium.tasks.schema`) and pack loader
  (`cambium.tasks.pack`) impose no assumption about pack size — growing to
  60 tasks means adding more `data/*.json` files in the same shape, not
  changing code.
- Held-out discipline is enforced by the loader regardless of scale: `split`
  is a required field per task, and nothing in the admission-gate or
  generation code path is allowed to read `pack.heldout` (enforced by
  convention now, worth a lint/test in Sprint 4 if this pack grows).
