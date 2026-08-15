from cambium.eval.harness import EvolutionConfig, run_evolution, score_frozen_snapshot
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()


def test_both_evolving_reaches_full_train_and_heldout_by_generation_3():
    result = run_evolution(PACK, EvolutionConfig(generations=4), "both")
    by_gen = {r.generation: r for r in result.records}

    assert by_gen[1].train_solved == 5
    assert by_gen[1].heldout_solved == 2  # library-off equivalent
    assert by_gen[2].train_solved == 18
    assert by_gen[2].num_active_skills == 7
    assert by_gen[2].heldout_solved == 8  # retrieval collision still costs 1
    assert by_gen[3].heldout_solved == 9  # planner mutation fixes it
    assert by_gen[4].heldout_solved == 9  # plateau


def test_tools_only_ablation_never_beats_library_off():
    """No reflector retry budget ever gets unlocked (evolve_prompts=False),
    so the flawed-first generation candidates never get a second try and
    nothing is ever admitted."""
    result = run_evolution(PACK, EvolutionConfig(generations=4, evolve_skills=True, evolve_prompts=False), "tools_only")
    for record in result.records:
        assert record.heldout_solved == 2
        assert record.num_active_skills == 0


def test_prompts_only_ablation_masters_train_but_gains_nothing_on_heldout():
    """The core result: fresh generation succeeding every time on train
    (persist_skills=False) does not transfer to held-out, because held-out
    is scored without a generation fallback. Only a persisted, admitted
    library moves the held-out number."""
    result = run_evolution(PACK, EvolutionConfig(generations=4, evolve_skills=False, evolve_prompts=True), "prompts_only")
    last = result.records[-1]
    assert last.train_solved == 18   # full train mastery via fresh generation
    assert last.heldout_solved == 2  # zero heldout lift -- nothing persisted


def test_frozen_snapshot_is_strictly_worse_than_continued_evolution():
    result = run_evolution(PACK, EvolutionConfig(generations=4), "both")
    frozen_at_2 = next(r for r in result.records if r.generation == 2)
    frozen_score = score_frozen_snapshot(frozen_at_2, PACK)
    live_at_4 = next(r for r in result.records if r.generation == 4)

    assert frozen_score["solved"] == 8
    assert live_at_4.heldout_solved == 9
    assert frozen_score["solved"] < live_at_4.heldout_solved
