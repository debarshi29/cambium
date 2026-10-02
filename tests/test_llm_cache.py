"""Record/replay for live LLM calls, and the harness driving the LLM agent
(docs/adr/0012). No network: an offline "oracle" chat client stands in for
the model, answering codegen prompts from the scripted candidate bank."""
import functools
import json
import re

import pytest

from cambium.agent.generation import CANDIDATE_BANK
from cambium.agent.llm_cache import LLMCacheMiss, RecordReplayClient, request_key
from cambium.agent.loop import run_task_llm
from cambium.cli import main
from cambium.eval.experiments import run_full_eval
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()
_FN_TO_CATEGORY = {t.fn_name: t.category for t in PACK.tasks}
_NAMED_RE = re.compile(r"must be named `(\w+)`")


class OracleChat:
    """Answers like a competent model: the first codegen attempt for a task
    returns the bank's (flawed) first candidate, a retry-with-feedback
    returns the correct one. Critic prompts are answered GENERAL."""

    model = "oracle-test-model"
    temperature = 0.0
    max_tokens = 800

    def __init__(self):
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        if "GENERAL or OVERFIT" in system:
            return "GENERAL"
        fn = _NAMED_RE.search(user).group(1)
        bank = CANDIDATE_BANK[_FN_TO_CATEGORY[fn]]
        source = bank[1] if "previous attempt failed" in user else bank[0]
        return f"```python\n{source}\n```"


def test_record_then_replay_offline(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    oracle = OracleChat()
    rec = RecordReplayClient(cassette, mode="record", inner=oracle)
    a = rec.chat("sys", "Task: x\nThe function must be named `fib_n`.")
    assert oracle.calls == 1 and rec.calls == 1

    replay = RecordReplayClient(cassette, mode="replay", model=oracle.model,
                                temperature=oracle.temperature, max_tokens=oracle.max_tokens)
    assert replay.chat("sys", "Task: x\nThe function must be named `fib_n`.") == a
    assert replay.hits == 1


def test_replay_miss_raises_instead_of_going_live(tmp_path):
    replay = RecordReplayClient(tmp_path / "empty.jsonl", mode="replay", model="m")
    with pytest.raises(LLMCacheMiss):
        replay.chat("sys", "never recorded")


def test_auto_mode_only_calls_on_miss(tmp_path):
    oracle = OracleChat()
    auto = RecordReplayClient(tmp_path / "c.jsonl", mode="auto", inner=oracle)
    for _ in range(3):
        auto.chat("GENERAL or OVERFIT", "q")
    assert oracle.calls == 1 and auto.hits == 2


def test_key_covers_every_request_parameter():
    base = request_key("m", 0.2, 800, "s", "u")
    assert base != request_key("m2", 0.2, 800, "s", "u")
    assert base != request_key("m", 0.3, 800, "s", "u")
    assert base != request_key("m", 0.2, 801, "s", "u")
    assert base != request_key("m", 0.2, 800, "s2", "u")
    assert base != request_key("m", 0.2, 800, "s", "u2")


def test_cassette_is_a_readable_prompt_log(tmp_path):
    cassette = tmp_path / "c.jsonl"
    RecordReplayClient(cassette, mode="record", inner=OracleChat()).chat("GENERAL or OVERFIT?", "the user")
    entry = json.loads(cassette.read_text(encoding="utf-8").splitlines()[0])
    assert entry["system"] == "GENERAL or OVERFIT?" and entry["user"] == "the user"
    assert entry["model"] == "oracle-test-model"


def test_record_and_auto_need_an_inner_client(tmp_path):
    with pytest.raises(ValueError):
        RecordReplayClient(tmp_path / "c.jsonl", mode="record")
    with pytest.raises(ValueError):
        RecordReplayClient(tmp_path / "c.jsonl", mode="bogus", inner=OracleChat())


def _llm_eval(client):
    runner = functools.partial(run_task_llm, client=client)
    return run_full_eval(PACK, generations=3, freeze_at=1, task_runner=runner).report


def test_harness_runs_on_the_llm_agent_and_replays_identically(tmp_path):
    """The fourth curve's mechanics: the full eval (three curves + ablation
    + audit) driven through run_task_llm, recorded, then replayed offline
    with no model at all -- and the replayed report is identical."""
    cassette = tmp_path / "eval.jsonl"
    recorded = _llm_eval(RecordReplayClient(cassette, mode="record", inner=OracleChat()))
    replayed = _llm_eval(RecordReplayClient(cassette, mode="replay", model=OracleChat.model,
                                            temperature=0.0, max_tokens=800))
    assert recorded == replayed

    # With retry-with-feedback the oracle needs the reflector's raised budget,
    # exactly like the scripted agent: the same ablation shape falls out.
    both = recorded["curve_2_library_on_evolving"]
    assert both[-1]["heldout_solved"] == 20
    assert recorded["ablation"]["tools_only"][-1]["heldout_solved"] == 3
    assert recorded["ablation"]["prompts_only"][-1]["heldout_solved"] == 3


def test_cli_replay_without_cassette_entry_is_a_clean_error(tmp_path, capsys):
    rc = main(["eval", "--agent", "llm", "--llm-mode", "replay", "--llm-cache",
               str(tmp_path / "missing.jsonl"), "--generations", "1", "--freeze-at", "1",
               "--no-mlflow", "--out", str(tmp_path)])
    assert rc == 2
    assert "not on cassette" in capsys.readouterr().err


def test_cli_replay_requires_a_cassette(tmp_path, capsys):
    rc = main(["eval", "--agent", "llm", "--llm-mode", "replay", "--generations", "1",
               "--freeze-at", "1", "--no-mlflow", "--out", str(tmp_path)])
    assert rc == 2
    assert "--llm-cache" in capsys.readouterr().err


def test_cli_replay_finds_what_the_cli_client_recorded(tmp_path, monkeypatch):
    """Regression: CLI replay built its cassette key with temperature=0 and
    max_tokens=0, while recording used the client's real values (0.2,
    800/4096), so replay could never hit a recorded prompt."""
    from argparse import Namespace

    from cambium.agent.llm_client import LLMClient
    from cambium.cli import _llm_client

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    cassette = tmp_path / "c.jsonl"
    live = LLMClient()
    oracle = OracleChat()
    oracle.model, oracle.temperature, oracle.max_tokens = live.model, live.temperature, live.max_tokens
    RecordReplayClient(cassette, mode="record", inner=oracle).chat("GENERAL or OVERFIT?", "the user")

    monkeypatch.delenv("GEMINI_API_KEY")  # replay must work with no key at all
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    replay = _llm_client(Namespace(provider=None, model=None, llm_mode="replay",
                                   llm_cache=str(cassette)))
    assert replay.chat("GENERAL or OVERFIT?", "the user") == "GENERAL"
