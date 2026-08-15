"""Sprint 5: the eval harness. Produces the three curves (CLAUDE.md §4),
the tools-vs-prompts attribution ablation, the reward-hacking audit, and
MLflow lineage for the whole run.

Run:
    python scripts/run_eval.py
"""
import _pathfix  # noqa: F401
import json
from pathlib import Path

from cambium.agent.solver import BaseSolver
from cambium.eval import lineage
from cambium.eval.hacking_audit import run_audit
from cambium.eval.harness import EvolutionConfig, run_evolution, score_frozen_snapshot
from cambium.sandbox.runner import run_in_sandbox
from cambium.tasks.pack import load_task_pack

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "eval_report.json"
GENERATIONS = 4
FREEZE_AT_GENERATION = 2


def library_off_heldout(pack) -> dict:
    solver = BaseSolver()
    solved = 0
    for task in pack.heldout:
        attempt = solver.attempt(task)
        if attempt.solved and run_in_sandbox(attempt.source, attempt.fn_name, task.cases_as_dicts()).ok:
            solved += 1
    return {"solved": solved, "total": len(pack.heldout)}


def curve_series(result) -> list:
    return [
        {
            "generation": r.generation,
            "train_rate": r.train_solved / r.train_total,
            "heldout_rate": r.heldout_solved / r.heldout_total,
            "heldout_solved": r.heldout_solved, "heldout_total": r.heldout_total,
            "num_active_skills": r.num_active_skills,
            "recall_at_1": r.recall_at_1, f"recall_at_{r.k}": r.recall_at_k,
        }
        for r in result.records
    ]


def main():
    pack = load_task_pack()

    report = {"pack": {"train": len(pack.train), "heldout": len(pack.heldout)}}

    # Curve 1: library-off
    off = library_off_heldout(pack)
    report["curve_1_library_off"] = off
    print(f"curve 1 (library-off) heldout: {off['solved']}/{off['total']}")

    # Curve 2: library-on, evolving (both skills and prompts)
    both = run_evolution(pack, EvolutionConfig(generations=GENERATIONS, evolve_skills=True, evolve_prompts=True), "both")
    report["curve_2_library_on_evolving"] = curve_series(both)
    print("curve 2 (library-on, evolving) heldout by generation:")
    for r in both.records:
        print(f"  gen {r.generation}: {r.heldout_solved}/{r.heldout_total}  "
              f"(train {r.train_solved}/{r.train_total}, skills={r.num_active_skills}, "
              f"recall@1={r.recall_at_1:.0%}, recall@{r.k}={r.recall_at_k:.0%})")

    # Curve 3: library frozen at FREEZE_AT_GENERATION, evaluated going forward
    frozen_record = next(r for r in both.records if r.generation == FREEZE_AT_GENERATION)
    frozen_score = score_frozen_snapshot(frozen_record, pack)
    report["curve_3_frozen_at_gen"] = {"frozen_at": FREEZE_AT_GENERATION, **frozen_score}
    print(f"curve 3 (frozen at gen {FREEZE_AT_GENERATION}): {frozen_score['solved']}/{frozen_score['total']}, "
          f"held constant vs. live curve 2 continuing to gen {GENERATIONS}")

    # Attribution ablation: tools-only, prompts-only, both (== curve 2)
    tools_only = run_evolution(pack, EvolutionConfig(generations=GENERATIONS, evolve_skills=True, evolve_prompts=False), "tools_only")
    prompts_only = run_evolution(pack, EvolutionConfig(generations=GENERATIONS, evolve_skills=False, evolve_prompts=True), "prompts_only")
    report["ablation"] = {
        "tools_only": curve_series(tools_only),
        "prompts_only": curve_series(prompts_only),
        "both": curve_series(both),
    }
    print("\nattribution ablation, final generation heldout rate:")
    for name, res in (("tools_only", tools_only), ("prompts_only", prompts_only), ("both", both)):
        last = res.records[-1]
        print(f"  {name}: {last.heldout_solved}/{last.heldout_total}")

    # Reward-hacking audit
    findings = run_audit(both.records[-1].skill_registry, both.admission_log)
    report["hacking_audit"] = [
        {"kind": f.kind, "subject": f.subject, "detail": f.detail} for f in findings
    ]
    print(f"\nreward-hacking audit: {len(findings)} finding(s)")
    for f in findings:
        print(f"  [{f.kind}] {f.subject}: {f.detail}")

    # MLflow lineage for the "both evolving" run
    with lineage.evolution_run("both-evolving", {"generations": GENERATIONS, "pack_train": len(pack.train), "pack_heldout": len(pack.heldout)}):
        for r in both.records:
            with lineage.generation_run(r.generation):
                lineage.log_generation_metrics(
                    r.generation, r.train_solved, r.train_total, r.heldout_solved, r.heldout_total,
                    r.num_active_skills, r.recall_at_1, r.recall_at_k, r.k,
                )
                lineage.log_library_snapshot(r.generation, r.skill_registry, r.prompt_registry)

    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwritten to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
