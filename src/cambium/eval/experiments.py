"""Library entry points for every reproducible experiment in this repo.

These used to live in `scripts/*.py` as `main()` bodies, which meant the
only way to run an experiment was as a script from a checkout. They now
live here, return plain data, and are driven by the `cambium` CLI
(cambium.cli); the scripts are thin wrappers kept for the README's
existing commands.

Nothing here prints. Callers decide how to present results.
"""
from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from pathlib import Path

from cambium import __version__
from cambium.agent.solver import BaseSolver
from cambium.eval.hacking_audit import run_audit
from cambium.eval.harness import (
    EvolutionConfig,
    EvolutionResult,
    run_evolution,
    score_frozen_snapshot,
)
from cambium.sandbox.runner import get_default_backend, run_in_sandbox
from cambium.tasks.pack import TaskPack

log = logging.getLogger(__name__)

DEFAULT_GENERATIONS = 4
DEFAULT_FREEZE_AT = 2


def run_metadata() -> dict:
    """Deterministic run metadata (no timestamps, no hostnames) so a re-run
    of the same code produces a byte-identical report."""
    return {
        "cambium_version": __version__,
        "python": platform.python_version(),
        "sandbox_backend": get_default_backend().name,
    }


def score_baseline_split(tasks: list) -> dict:
    solver = BaseSolver()
    per_task = {}
    for task in tasks:
        attempt = solver.attempt(task)
        if not attempt.solved or attempt.source is None:
            per_task[task.id] = {"solved": False, "reason": "agent_could_not_attempt"}
            continue
        result = run_in_sandbox(attempt.source, attempt.fn_name, task.cases_as_dicts())
        per_task[task.id] = {"solved": result.ok, "reason": result.reason}
    solved = sum(1 for r in per_task.values() if r["solved"])
    return {
        "solved": solved,
        "total": len(tasks),
        "rate": solved / len(tasks) if tasks else 0.0,
        "per_task": per_task,
    }


def run_baseline(pack: TaskPack) -> dict:
    """Curve 1 on its own: library-off, no admission/generation machinery."""
    return {"train": score_baseline_split(pack.train), "heldout": score_baseline_split(pack.heldout)}


def curve_series(result: EvolutionResult) -> list:
    return [
        {
            "generation": r.generation,
            "train_rate": r.train_solved / r.train_total,
            "heldout_rate": r.heldout_solved / r.heldout_total,
            "heldout_solved": r.heldout_solved,
            "heldout_total": r.heldout_total,
            "num_active_skills": r.num_active_skills,
            "recall_at_1": r.recall_at_1,
            f"recall_at_{r.k}": r.recall_at_k,
        }
        for r in result.records
    ]


@dataclass
class EvalOutcome:
    report: dict
    both: EvolutionResult
    tools_only: EvolutionResult
    prompts_only: EvolutionResult
    findings: list = field(default_factory=list)


def run_full_eval(
    pack: TaskPack,
    generations: int = DEFAULT_GENERATIONS,
    freeze_at: int = DEFAULT_FREEZE_AT,
    task_runner=None,
) -> EvalOutcome:
    """The three curves, the tools-vs-prompts ablation, and the hacking
    audit (CLAUDE.md §4). MLflow logging is separate (`log_lineage`) so
    this stays a pure computation. `task_runner` swaps the scripted agent
    for another one with run_task's signature, e.g. the live LLM
    (docs/adr/0012)."""

    def config(**kw) -> EvolutionConfig:
        return EvolutionConfig(generations=generations, task_runner=task_runner, **kw)

    if not 1 <= freeze_at <= generations:
        raise ValueError(f"freeze_at must be in [1, {generations}], got {freeze_at}")

    report: dict = {"pack": {"train": len(pack.train), "heldout": len(pack.heldout)}}

    log.info("curve 1: library-off")
    off = score_baseline_split(pack.heldout)
    report["curve_1_library_off"] = {"solved": off["solved"], "total": off["total"]}

    log.info("curve 2: library-on, both evolving (%d generations)", generations)
    both = run_evolution(pack, config(), "both")
    report["curve_2_library_on_evolving"] = curve_series(both)

    frozen_record = next(r for r in both.records if r.generation == freeze_at)
    report["curve_3_frozen_at_gen"] = {"frozen_at": freeze_at, **score_frozen_snapshot(frozen_record, pack)}

    log.info("ablation: tools-only")
    tools_only = run_evolution(pack, config(evolve_skills=True, evolve_prompts=False), "tools_only")
    log.info("ablation: prompts-only")
    prompts_only = run_evolution(pack, config(evolve_skills=False, evolve_prompts=True), "prompts_only")
    report["ablation"] = {
        "tools_only": curve_series(tools_only),
        "prompts_only": curve_series(prompts_only),
        "both": curve_series(both),
    }

    findings = run_audit(both.records[-1].skill_registry, both.admission_log)
    report["hacking_audit"] = [{"kind": f.kind, "subject": f.subject, "detail": f.detail} for f in findings]
    log.info("hacking audit: %d finding(s)", len(findings))

    return EvalOutcome(report, both, tools_only, prompts_only, findings)


def log_lineage(outcome: EvalOutcome, pack: TaskPack, tracking_uri: str | None = None,
                run_name: str = "both-evolving", extra_params: dict | None = None) -> None:
    """MLflow lineage for the both-evolving run (CLAUDE.md §6)."""
    from cambium.eval import lineage

    params = {
        "generations": len(outcome.both.records),
        "pack_train": len(pack.train),
        "pack_heldout": len(pack.heldout),
        **run_metadata(),
        **(extra_params or {}),
    }
    with lineage.evolution_run(run_name, params, tracking_uri=tracking_uri):
        for r in outcome.both.records:
            with lineage.generation_run(r.generation):
                lineage.log_generation_metrics(
                    r.generation, r.train_solved, r.train_total, r.heldout_solved, r.heldout_total,
                    r.num_active_skills, r.recall_at_1, r.recall_at_k, r.k,
                )
                lineage.log_library_snapshot(r.generation, r.skill_registry, r.prompt_registry)


def default_results_dir() -> Path:
    """`results/` next to the source checkout when run from one, else the
    current directory's `results/` (an installed package has no checkout)."""
    checkout = Path(__file__).resolve().parents[3]
    if (checkout / "pyproject.toml").exists() and (checkout / "src" / "cambium").exists():
        return checkout / "results"
    return Path.cwd() / "results"


__all__ = [
    "DEFAULT_FREEZE_AT",
    "DEFAULT_GENERATIONS",
    "EvalOutcome",
    "curve_series",
    "default_results_dir",
    "log_lineage",
    "run_baseline",
    "run_full_eval",
    "run_metadata",
    "score_baseline_split",
]
