"""Run the whole project end to end: baseline, generation+admission demo,
recall@k demo, curation demo, then the full eval harness. This is the
single command for "someone else can clone and reproduce" (CLAUDE.md
Sprint 6's done-when criterion).

Run:
    python scripts/demo.py
"""
import subprocess
import sys
from pathlib import Path

import _pathfix  # noqa: F401

SCRIPTS_DIR = Path(__file__).resolve().parent
STEPS = [
    ("Sprint 1: library-off baseline", "run_baseline.py"),
    ("Sprint 2: generation + admission gates", "run_generation_demo.py"),
    ("Sprint 3: recall@k", "run_recall_demo.py"),
    ("Sprint 4: curation", "run_curation_demo.py"),
    ("Sprint 5: full eval harness (three curves + ablation)", "run_eval.py"),
    ("Curation stress test: 25 generations, curated vs. uncurated", "run_curation_stress.py"),
]


def main():
    for title, script in STEPS:
        print("\n" + "=" * 72, flush=True)
        print(title, flush=True)
        print("=" * 72, flush=True)
        result = subprocess.run([sys.executable, str(SCRIPTS_DIR / script)])
        if result.returncode != 0:
            print(f"\n{script} exited {result.returncode} -- stopping.")
            sys.exit(result.returncode)
    print("\n" + "=" * 72)
    print("done. See results/baseline.json, results/eval_report.json, "
          "and mlruns.db (mlflow ui --backend-store-uri sqlite:///mlruns.db) "
          "for full output.")


if __name__ == "__main__":
    main()
