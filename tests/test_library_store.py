import json

import pytest

from cambium.curation.curator import run_curation
from cambium.eval.harness import EvolutionConfig, run_evolution
from cambium.library.store import (
    SCHEMA_VERSION,
    LibraryStoreError,
    load_library,
    save_library,
)
from cambium.prompts.defaults import seed_default_registry
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.skills.schema import Skill
from cambium.tasks.pack import load_task_pack


def make_skill(name="fib_skill", version=1, source=None):
    return Skill(
        name=name,
        signature="fib_n(...)",
        docstring="Return the nth Fibonacci number.",
        source=source or "def fib_n(n):\n    return n",
        fn_name="fib_n",
        tests=({"args": [1], "kwargs": {}, "expected": 1},),
        provenance={"task_id": "fibonacci_1", "generation": 1, "category": "fibonacci"},
        version=version,
    )


def test_roundtrip_preserves_full_history_including_deprecated(tmp_path):
    skills = SkillRegistry()
    skills.add(make_skill(version=1))
    skills.add(make_skill(version=2, source="def fib_n(n):\n    return n + 0"))
    skills.deprecate("fib_skill", 1, reason="superseded by v2")
    skills.record_use("fib_skill", generation=3, success=True)
    prompts = seed_default_registry()

    path = save_library(tmp_path / "lib.json", skills, prompts, generation=3, metadata={"run": "t"})
    snap = load_library(path)

    assert snap.generation == 3
    assert snap.metadata == {"run": "t"}
    versions = snap.skills.all_versions("fib_skill")
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].deprecated and versions[0].deprecation_reason == "superseded by v2"
    assert snap.skills.get_active("fib_skill").stats.invocations == 1
    assert snap.skills.to_dict() == skills.to_dict()
    assert snap.prompts.to_dict() == prompts.to_dict()


def test_loaded_prompts_keep_working_params(tmp_path):
    prompts = seed_default_registry()
    prompts.add(Prompt(
        name="reflector-v2", node="reflector", template="Retry up to max_attempts=3 time(s).",
        docstring="d", eval_task_ids=("a", "b"), provenance={"parent": "x", "generation": 2},
        version=2,
    ))
    snap = load_library(save_library(tmp_path / "lib.json", SkillRegistry(), prompts))
    active = snap.prompts.active("reflector")
    assert active.params() == {"max_attempts": 3}
    assert active.eval_task_ids == ("a", "b")


def test_tampered_source_is_rejected(tmp_path):
    skills = SkillRegistry()
    skills.add(make_skill())
    path = save_library(tmp_path / "lib.json", skills, seed_default_registry())

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["skills"]["skills"][0]["source"] = "def fib_n(n):\n    import os\n    return 0"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(LibraryStoreError, match="fingerprint"):
        load_library(path)


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION + 1}), encoding="utf-8")
    with pytest.raises(LibraryStoreError, match="schema_version"):
        load_library(path)


def test_garbage_file_is_a_store_error_and_missing_file_is_not(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(LibraryStoreError):
        load_library(bad)
    with pytest.raises(FileNotFoundError):
        load_library(tmp_path / "missing.json")


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    save_library(tmp_path / "lib.json", SkillRegistry(), seed_default_registry())
    save_library(tmp_path / "lib.json", SkillRegistry(), seed_default_registry())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["lib.json"]


def test_curation_reasons_are_recorded_for_prompts():
    prompts = seed_default_registry()
    prompts.add(Prompt(
        name="reflector-v2", node="reflector", template="max_attempts=2",
        docstring="d", eval_task_ids=(), provenance={}, version=2,
    ))
    run_curation(SkillRegistry(), prompts, generation=2)
    v1 = prompts.all_versions("reflector")[0]
    assert v1.deprecated and v1.deprecation_reason == "superseded"


def test_evolved_library_survives_roundtrip_and_still_scores_the_same(tmp_path):
    from cambium.eval.scoring import score_tasks

    pack = load_task_pack()
    result = run_evolution(pack, EvolutionConfig(generations=3), "persist")
    last = result.records[-1]
    path = save_library(tmp_path / "lib.json", last.skill_registry, last.prompt_registry, 3)
    snap = load_library(path)

    heldout = tuple(t.id for t in pack.heldout)
    before = score_tasks(heldout, last.skill_registry, last.prompt_registry.active("planner"), pack)
    after = score_tasks(heldout, snap.skills, snap.prompts.active("planner"), pack)
    assert before == after
