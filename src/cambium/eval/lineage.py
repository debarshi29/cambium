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

import os
from contextlib import contextmanager

# MLflow 3.x prints an "agent hint" banner on import; it's noise in a CLI.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402

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
            {
                "name": s.name, "version": s.version, "fingerprint": s.fingerprint(),
                "provenance": s.provenance, "stats": s.stats.to_dict(),
            }
            for s in skill_registry.active()
        ],
        "active_prompts": {
            node: {"version": prompt_registry.active(node).version, "params": prompt_registry.active(node).params()}
            for node in ("planner", "reflector", "critic")
        },
    }
    mlflow.log_dict(snapshot, f"snapshots/generation_{generation}.json")
    # Full, reloadable library (cambium.library.store format) alongside the
    # summary above -- the summary is for eyeballing in the MLflow UI, this
    # is for `cambium.library.load_library` on the downloaded artifact.
    from cambium.library.store import LibrarySnapshot

    full = LibrarySnapshot(skill_registry, prompt_registry, generation).to_dict()
    mlflow.log_dict(full, f"libraries/generation_{generation}.json")
