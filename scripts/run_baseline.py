"""library-off baseline: score the agent with no skill library at all.

This is curve 1 of CLAUDE.md §4's three curves. Run:
    python scripts/run_baseline.py
"""
import _pathfix  # noqa: F401  (must precede cambium imports)
import json
from pathlib import Path

from cambium.agent.solver import BaseSolver
from cambium.sandbox.runner import run_in_sandbox
from cambium.tasks.pack import load_task_pack

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "baseline.json"


def score_split(solver: BaseSolver, tasks: list) -> dict:
    per_task = {}
    for task in tasks:
        attempt = solver.attempt(task)
        if not attempt.solved:
            per_task[task.id] = {"solved": False, "reason": "agent_could_not_attempt"}
            continue
        result = run_in_sandbox(attempt.source, attempt.fn_name, task.cases_as_dicts())
        per_task[task.id] = {"solved": result.ok, "reason": result.reason}
    solved = sum(1 for r in per_task.values() if r["solved"])
    return {"solved": solved, "total": len(tasks), "rate": solved / len(tasks) if tasks else 0.0, "per_task": per_task}


def main():
    pack = load_task_pack()
    solver = BaseSolver()
    report = {
        "train": score_split(solver, pack.train),
        "heldout": score_split(solver, pack.heldout),
    }
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"train:   {report['train']['solved']}/{report['train']['total']} "
          f"({report['train']['rate']:.0%})")
    print(f"heldout: {report['heldout']['solved']}/{report['heldout']['total']} "
          f"({report['heldout']['rate']:.0%})")
    print(f"written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
