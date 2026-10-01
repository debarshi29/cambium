"""MLflow lineage against a throwaway sqlite store: one parent run, one
nested run per generation, metrics + a reloadable library per generation."""
import json

import pytest

mlflow = pytest.importorskip("mlflow")

from cambium.eval.experiments import log_lineage, run_full_eval  # noqa: E402
from cambium.library.store import LibrarySnapshot  # noqa: E402
from cambium.tasks.pack import load_task_pack  # noqa: E402


def test_lineage_logs_parent_and_generation_runs(tmp_path):
    pack = load_task_pack()
    outcome = run_full_eval(pack, generations=2, freeze_at=1)
    uri = f"sqlite:///{(tmp_path / 'mlruns.db').as_posix()}"

    log_lineage(outcome, pack, tracking_uri=uri, run_name="lineage-test", extra_params={"note": "t"})

    client = mlflow.tracking.MlflowClient(tracking_uri=uri)
    exp = client.get_experiment_by_name("cambium-evolution")
    runs = client.search_runs([exp.experiment_id])
    parents = [r for r in runs if r.data.tags.get("mlflow.runName") == "lineage-test"]
    children = [r for r in runs if r.data.tags.get("mlflow.parentRunId") == parents[0].info.run_id]

    assert len(parents) == 1
    assert parents[0].data.params["note"] == "t"
    assert parents[0].data.params["pack_heldout"] == "20"
    assert sorted(int(c.data.params["generation"]) for c in children) == [1, 2]

    gen2 = next(c for c in children if c.data.params["generation"] == "2")
    assert gen2.data.metrics["heldout_solved"] == 19
    assert gen2.data.metrics["num_active_skills"] == 17

    path = mlflow.artifacts.download_artifacts(
        run_id=gen2.info.run_id, artifact_path="libraries/generation_2.json",
        dst_path=str(tmp_path / "dl"), tracking_uri=uri,
    )
    with open(path, encoding="utf-8") as fh:
        snap = LibrarySnapshot.from_dict(json.load(fh))
    assert len(snap.skills) == 17
