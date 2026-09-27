"""Curation stress test: 25 generations of noisy near-duplicate proposals,
curated vs. uncurated (cambium.eval.stress, docs/adr/0011).

Run:
    python scripts/run_curation_stress.py
"""
import json
from dataclasses import asdict
from pathlib import Path

import _pathfix  # noqa: F401

from cambium.eval.stress import StressConfig, run_stress
from cambium.sandbox.cache import enable_default_cache
from cambium.tasks.pack import load_task_pack

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "curation_stress.json"


def summarize(label, result):
    print(f"\n{label}")
    print("  gen  admitted  active  versions  heldout  recall@1  recall@k")
    for r in result.records:
        print(f"  {r.generation:>3}  {r.admitted:>8}  {r.active_skills:>6}  {r.total_versions:>8}  "
              f"{r.heldout_solved:>3}/{r.heldout_total:<3}  {r.recall_at_1:>7.0%}  {r.recall_at_k:>7.0%}")


def main():
    enable_default_cache()  # scripted candidates: deterministic verdicts
    pack = load_task_pack()
    curated = run_stress(pack, StressConfig(curation=True))
    uncurated = run_stress(pack, StressConfig(curation=False))
    summarize("curated", curated)
    summarize("uncurated", uncurated)

    report = {
        "config": asdict(curated.config),
        "curated": [r.to_dict() for r in curated.records],
        "uncurated": [r.to_dict() for r in uncurated.records],
    }
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\nwritten to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
