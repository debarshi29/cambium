"""MLflow lineage. CLAUDE.md §6: "MLflow 3.0 carries generation lineage —
every generation logs skill library state, prompt library state, scores,
and retrieval metrics as a linked run."

Uses mlflow-skinny (the real `mlflow` package, minus the heavy server/UI
extras) against a local file store under ./mlruns — no tracking server
needed. One parent run for the whole evolution; one nested child run per
generation, so every generation's metrics are queryable individually but
linked under a common lineage.
"""
from __future__ import annotations

from contextlib import contextmanager

import mlflow

EXPERIMENT_NAME = "cambium-evolution"


def configure():
    # mlflow-skinny's filesystem backend ("file:./mlruns") is in maintenance
    # mode as of mlflow 3.x and raises unless opted back into explicitly;
    # sqlite is what MLflow itself recommends instead. Local file, still no
    # tracking server required.
    mlflow.set_tracking_uri("sqlite:///mlruns.db")
    mlflow.set_experiment(EXPERIMENT_NAME)


@contextmanager
def evolution_run(run_name: str, params: dict):
    configure()
    with mlflow.start_run(run_name=run_name) as parent:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        yield parent


@contextmanager
def generation_run(generation: int):
    with mlflow.start_run(run_name=f"generation-{generation}", nested=True) as child:
        mlflow.log_param("generation", generation)
        yield child


def log_generation_metrics(
    generation: int,
    train_solved: int,
    train_total: int,
    heldout_solved: int,
    heldout_total: int,
    num_active_skills: int,
    recall_at_1: float,
    recall_at_k: float,
    k: int,
) -> None:
    mlflow.log_metrics({
        "train_solved": train_solved,
        "train_rate": train_solved / train_total if train_total else 0.0,
        "heldout_solved": heldout_solved,
        "heldout_rate": heldout_solved / heldout_total if heldout_total else 0.0,
        "num_active_skills": num_active_skills,
        "recall_at_1": recall_at_1,
        f"recall_at_{k}": recall_at_k,
    }, step=generation)


def log_library_snapshot(generation: int, skill_registry, prompt_registry) -> None:
    snapshot = {
        "generation": generation,
        "active_skills": [
            {"name": s.name, "version": s.version, "provenance": s.provenance, "stats": vars(s.stats)}
            for s in skill_registry.active()
        ],
        "active_prompts": {
            node: {"version": prompt_registry.active(node).version, "params": prompt_registry.active(node).params()}
            for node in ("planner", "reflector", "critic")
        },
    }
    mlflow.log_dict(snapshot, f"snapshots/generation_{generation}.json")
