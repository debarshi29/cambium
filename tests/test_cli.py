import json
import shutil
from pathlib import Path

import pytest

from cambium import __version__
from cambium.cli import build_parser, main

REPO = Path(__file__).resolve().parent.parent
COMMITTED_LIBRARY = REPO / "results" / "library_both_evolving.json"


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_every_command_has_help():
    parser = build_parser()
    for argv in (["eval"], ["baseline"], ["stress"], ["llm-demo"], ["tasks"],
                 ["library", "show", "x"], ["library", "diff", "a", "b"]):
        assert parser.parse_args(argv).func is not None


def test_tasks_lists_the_pack(capsys):
    assert main(["tasks", "--split", "heldout"]) == 0
    out = capsys.readouterr().out
    assert "20 task(s)" in out
    assert "fibonacci_3" in out


def test_baseline_writes_report(tmp_path, capsys):
    assert main(["baseline", "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))
    assert report["heldout"]["solved"] == 3
    assert report["heldout"]["total"] == 20


def test_short_eval_writes_report_and_reloadable_library(tmp_path, capsys):
    assert main(["eval", "--generations", "2", "--freeze-at", "1", "--no-mlflow",
                 "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert [r["generation"] for r in report["curve_2_library_on_evolving"]] == [1, 2]
    assert report["curve_3_frozen_at_gen"]["frozen_at"] == 1
    assert main(["library", "show", str(tmp_path / "library_both_evolving.json")]) == 0
    assert "fibonacci_skill@v1" in capsys.readouterr().out


def test_bad_freeze_point_is_a_clean_error(tmp_path, capsys):
    rc = main(["eval", "--generations", "2", "--freeze-at", "5", "--no-mlflow", "--out", str(tmp_path)])
    assert rc == 2
    assert "freeze_at" in capsys.readouterr().err


def test_library_diff_identical_and_changed(tmp_path, capsys):
    assert main(["library", "diff", str(COMMITTED_LIBRARY), str(COMMITTED_LIBRARY), "--exit-code"]) == 0
    assert "identical" in capsys.readouterr().out

    changed = tmp_path / "changed.json"
    raw = json.loads(COMMITTED_LIBRARY.read_text(encoding="utf-8"))
    raw["skills"]["skills"] = [s for s in raw["skills"]["skills"] if s["name"] != "fibonacci_skill"]
    changed.write_text(json.dumps(raw), encoding="utf-8")
    assert main(["library", "diff", str(COMMITTED_LIBRARY), str(changed), "--exit-code"]) == 1
    assert "- fibonacci_skill" in capsys.readouterr().out


def test_missing_library_file_is_a_clean_error(tmp_path, capsys):
    assert main(["library", "show", str(tmp_path / "nope.json")]) == 2
    assert "error:" in capsys.readouterr().err


def test_unusable_sandbox_is_a_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CAMBIUM_DOCKER", "definitely-not-docker")
    assert main(["baseline", "--sandbox", "docker", "--out", str(tmp_path)]) == 2
    assert "docker" in capsys.readouterr().err


def test_custom_task_dir(tmp_path, capsys):
    src = REPO / "src" / "cambium" / "tasks" / "data"
    for name in ("fibonacci_1.json", "fibonacci_2.json"):
        shutil.copy(src / name, tmp_path / name)
    assert main(["tasks", "--tasks", str(tmp_path)]) == 0
    assert "2 task(s)" in capsys.readouterr().out


def test_llm_demo_without_key_fails_cleanly(capsys):
    # conftest clears every provider key, so this must fail before any request
    assert main(["llm-demo", "--limit", "4"]) == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_llm_demo_names_the_gemini_key_when_gemini_is_chosen(capsys):
    assert main(["llm-demo", "--provider", "gemini", "--limit", "1"]) == 2
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err and "aistudio.google.com" in err
