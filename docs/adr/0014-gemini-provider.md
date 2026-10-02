# ADR 0014: Gemini API as a second LLM provider (Gemma 4 31B)

## Status
Accepted. Extends [ADR 0007](0007-live-llm-integration.md) (live LLM) and
[ADR 0012](0012-llm-record-replay.md) (record/replay).

## Context
The live path was hardwired to Groq: one URL, one key variable
(`GROQ_API_KEY`), one default model. The project now has a Gemini API key
instead, and wants to drive the loop with Gemma 4 31B, which the Gemini
API serves as `gemma-4-31b-it`.

The Gemini API exposes an OpenAI-compatible chat-completions endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai/`), the same
wire format the Groq client already speaks. So this is a configuration
change, not a second client.

## Decision
- `cambium.agent.llm_client.LLMClient` with a small provider table:

  | provider | key | default model | default max_tokens |
  |---|---|---|---|
  | `gemini` | `GEMINI_API_KEY` | `gemma-4-31b-it` | 4096 |
  | `groq` | `GROQ_API_KEY` | `openai/gpt-oss-20b` | 800 |

  Provider = `--provider` / `LLM_PROVIDER`, else whichever key is set
  (Groq first, for backward compatibility). Model = `--model` / `LLM_MODEL`
  / `GEMINI_MODEL` or `GROQ_MODEL`, else the default.
- **Thinking-model tolerance.** Gemma 4 can reason before answering, so a
  reply may contain draft code and both verdict words. `extract_code` now
  takes the *last* fenced block, and the critic uses the *last*
  `GENERAL`/`OVERFIT` it finds. Gemini's default `max_tokens` is 4096 so
  reasoning doesn't truncate the answer.
- **Client errors fail fast.** A 4xx other than 408/429 (bad model id, bad
  key) is no longer retried; it raises `LLMConfigError` carrying the API's
  own message and, for 400/404, the provider's default model id. Found
  live: `GEMINI_MODEL="Gemma 4 31B"` (the display name, not the id) was
  retried three times and surfaced as a bare traceback.
- `GroqClient` and `GroqConfigError` remain as backward-compatible names;
  `GroqClient` stays pinned to Groq.

## Also fixed
`cambium eval --llm-mode replay` built its cassette keys with
`temperature=0, max_tokens=0`, while recording used the client's real
values, so a CLI replay could never find a CLI recording. Replay now
derives model, temperature and max_tokens from the same client
configuration that recorded (no key needed to build it).

The test suite now clears every provider key and model variable before
each test. `llm_client` loads `.env` on import, so without this a real key
in a developer's `.env` was visible to tests, and a "no key configured"
test could make a live, billed call.

## Verification
Live, against the Gemini API with `gemma-4-31b-it`: `cambium llm-demo
--limit 3` solved 3/3 tasks (`anagram_check_1`, `balanced_brackets_1`,
`caesar_cipher_1`) by live generation, and all three model-written skills
passed the admission gate's reuse check on a second task. Offline: 17 new
tests for provider selection, the request shape, parsing, fail-fast
errors and the replay fix.

## Consequences
- The reported scripted curves are unchanged. A live Gemma 4 curve is now
  one command away:
  `cambium eval --agent llm --provider gemini --llm-mode record --llm-cache results/llm_cassette.jsonl`.
- Gemini cassettes and Groq cassettes never collide: the model id is part
  of every cassette key.
