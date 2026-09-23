from cambium.agent.solver import BaseSolver
from cambium.sandbox.runner import run_in_sandbox
from cambium.tasks.pack import load_task_pack


def test_baseline_solves_exactly_base_capability_categories():
    pack = load_task_pack()
    solver = BaseSolver()
    base_categories = {"string_reverse", "word_count", "palindrome_check"}
    for task in pack.tasks:
        attempt = solver.attempt(task)
        assert attempt.solved == (task.category in base_categories), task.id


def test_baseline_solutions_actually_pass_sandbox():
    pack = load_task_pack()
    solver = BaseSolver()
    solved_count = 0
    for task in pack.tasks:
        attempt = solver.attempt(task)
        if attempt.solved:
            result = run_in_sandbox(attempt.source, attempt.fn_name, task.cases_as_dicts())
            assert result.ok, f"{task.id}: {result.stderr}"
            solved_count += 1
    assert solved_count == 9  # 3 base categories x 3 tasks each
