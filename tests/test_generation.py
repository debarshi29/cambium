from cambium.agent.generation import CANDIDATE_BANK, candidates_for
from cambium.sandbox.runner import run_in_sandbox
from cambium.tasks.pack import load_task_pack


def test_every_category_has_a_flawed_then_correct_pair():
    for category, sources in CANDIDATE_BANK.items():
        assert len(sources) == 2, category


def test_flawed_candidate_fails_its_own_origin_task_except_the_overfit_one():
    """Every flawed[0] candidate should fail sandbox verification against its
    own category's first train task — except run_length_encoding, whose
    candidate[0] is an overfit hack that *passes* its origin task (that's
    the point: the admission gate's reuse check has to catch it instead)."""
    pack = load_task_pack()
    for category in CANDIDATE_BANK:
        origin = next(t for t in pack.train if t.category == category)
        candidate = candidates_for(category)[0]
        result = run_in_sandbox(candidate.source, origin.fn_name, origin.cases_as_dicts())
        if category == "run_length_encoding":
            assert result.ok, "overfit candidate should pass its own origin task"
        else:
            assert not result.ok, f"{category}: flawed candidate unexpectedly passed"


def test_correct_candidate_passes_every_task_in_its_category():
    pack = load_task_pack()
    for category in CANDIDATE_BANK:
        candidate = candidates_for(category)[1]
        for task in pack.tasks:
            if task.category != category:
                continue
            result = run_in_sandbox(candidate.source, task.fn_name, task.cases_as_dicts())
            assert result.ok, f"{task.id}: {result.stderr}"


def test_overfit_candidate_fails_the_paired_train_task():
    pack = load_task_pack()
    other = pack.by_id("run_length_encoding_2")
    overfit = candidates_for("run_length_encoding")[0]
    result = run_in_sandbox(overfit.source, other.fn_name, other.cases_as_dicts())
    assert not result.ok
