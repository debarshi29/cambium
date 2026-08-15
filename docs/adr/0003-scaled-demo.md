# ADR 0003: Scaled-down task pack for this session's run

## Status
Accepted.

## Context
CLAUDE.md §4 specifies ~60 tasks, 40 train / 20 held-out. Producing that at
real scale means 60 hand-written, individually-verified programmatically-
checkable tasks plus enough per-category duplication for the reuse condition
in both admission gates — a multi-session effort on its own, independent of
the agent stand-in question (ADR 0002).

## Decision
This session ships a 20-task pack (14 train / 6 held-out — the same ~2:1
ratio as the full spec) across 10 categories, 2 tasks each. Every category
has exactly the duplication the admission gates' reuse condition needs
(CLAUDE.md §3.2 condition 4, §3.4 condition 3): one task to originate a
skill/prompt candidate on, at least one more to demonstrate reuse on. Three
categories (`string_reverse`, `word_count`, `palindrome_check`) are solvable
by the agent's base capabilities with no library at all, by design — this is
what makes the library-off baseline non-trivial (CLAUDE.md §4 curve 1)
instead of scoring zero, and what makes any measured lift from the library
attributable to the library rather than to the floor being zero.

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
