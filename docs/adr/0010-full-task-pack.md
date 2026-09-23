# ADR 0010: Task pack grown to spec size (60 tasks, 40 train / 20 held-out)

## Status
Accepted. Supersedes the scale decision in [ADR 0003](0003-scaled-demo.md);
ADR 0003's discipline rules (held-out never enters admission, ≥2 train tasks
per generated category) still apply unchanged.

## Context
CLAUDE.md §4 specifies ~60 tasks, 40 train / 20 held-out. The pack shipped
at 27 (18 / 9), and ADR 0006 listed growing it as "mechanical, not
architectural." That was true: no code path assumed the pack size except
one hardcoded tuple in the eval harness.

## Decision
20 categories × 3 tasks = 60 tasks, **every** category split 2 train + 1
held-out (the 3 base-capability categories included, which previously had
uneven 1/1 and 2/0 splits):

- the 10 original categories, plus `string_reverse_3`, `word_count_3`,
  `palindrome_check_3` to even out the base categories;
- 10 new generated categories spanning the domains §4 names:
  - data wrangling: `flatten_list`, `dedupe_ordered`, `merge_intervals`,
    `matrix_transpose`
  - format conversion / parsing: `csv_row_parse`, `query_string_parse`,
    `int_to_binary`
  - algorithmic: `anagram_check`, `digit_sum`, `balanced_brackets`

Each new category gets a two-entry scripted candidate bank (ADR 0002): a
plausibly-wrong first attempt (sets instead of multisets, one-level flatten,
square-only transpose, no sort before merging, naive `split(',')`, no URL
decoding, ...) and a correct second attempt. Every new task was checked so
the flawed candidate fails **every** train task in its category -- otherwise
a flawed candidate could solve one train task in a no-retry arm, get
proposed, and fail reuse on the other, which the hacking audit would then
misreport as overfitting.

The reflector's regression subset ("one train task per generated
category") is now derived from the pack (`reflector_regression_subset`)
instead of a hardcoded 7-tuple.

## Results at full scale
Re-running `scripts/run_eval.py` on the 60-task pack:

| curve | held-out |
|---|---:|
| library-off | 3/20 |
| library-on, evolving (gen 4) | 20/20 |
| frozen at gen 2 | 19/20 |
| tools-only | 3/20 |
| prompts-only | 3/20 (despite 40/40 train) |

The qualitative findings from the 27-task run all survive at spec scale:
both single-artifact ablations sit exactly at the library-off floor; the
same primality/fibonacci retrieval collision costs exactly one held-out task
at `top_k=1` (recall@1 48/51) until the planner mutation is admitted; the
overfit run-length-encoding candidate is rejected twice by the reuse check.

## Consequences
- Percentages are now "N of 20 held-out", and the library grows to 17
  active skills -- enough that retrieval collisions have more vocabulary to
  collide over, which the next retrieval work can measure against.
- One pre-existing quirk, documented rather than silently changed:
  `primality_3` (held-out) has no `n < 2` case, so the flawed primality
  candidate would pass it. Held-out tasks never go through generation, so
  this cannot affect any number above.
- The full test suite takes longer (the eval-harness tests run the whole
  60-task evolution); see the tooling work for parallel test execution.
