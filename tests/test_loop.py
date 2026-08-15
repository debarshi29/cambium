from cambium.agent.loop import run_task
from cambium.prompts.defaults import CRITIC_V1, PLANNER_V1, REFLECTOR_V1
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()


def _run(task_id, skill_registry, reflector=REFLECTOR_V1, generation=1):
    task = PACK.by_id(task_id)
    return run_task(task, generation, skill_registry, PLANNER_V1, reflector, CRITIC_V1, PACK)


def test_default_reflector_cannot_recover_from_a_flawed_first_attempt():
    registry = SkillRegistry()
    outcome = _run("fibonacci_1", registry)
    assert not outcome.solved
    assert outcome.strategy == "none"
    assert len(registry) == 0


def test_mutated_reflector_retries_and_solves_then_admits_a_skill():
    mutated_reflector = Prompt(
        name="reflector-retry-2", node="reflector",
        template="Retry with a new generation candidate up to max_attempts=2 time(s).",
        docstring="Allow one retry beyond the default.",
        eval_task_ids=(), provenance={"parent": "reflector-default@v1", "generation": 1},
        version=2,
    )
    registry = SkillRegistry()
    outcome = _run("fibonacci_1", registry, reflector=mutated_reflector)
    assert outcome.solved
    assert outcome.strategy == "generation"
    assert len(outcome.admission_attempts) == 1
    assert outcome.admission_attempts[0].admitted
    assert len(registry) == 1

    # second task in the category should now resolve via skill reuse, not
    # a fresh generation attempt
    second = _run("fibonacci_2", registry, reflector=mutated_reflector, generation=2)
    assert second.solved
    assert second.strategy == "skill_reuse"
    assert second.skill_used == "fibonacci_skill"


def test_overfit_candidate_solves_its_own_task_but_skill_is_rejected():
    registry = SkillRegistry()
    outcome = _run("run_length_encoding_1", registry)  # max_attempts=1 default is enough: overfit wins on attempt 0
    assert outcome.solved
    assert outcome.strategy == "generation"
    assert len(outcome.admission_attempts) == 1
    assert not outcome.admission_attempts[0].admitted
    assert outcome.admission_attempts[0].reason == "reuse_failed"
    assert len(registry) == 0  # nothing admitted


def test_eventual_general_skill_gets_admitted_from_the_second_task():
    mutated_reflector = Prompt(
        name="reflector-retry-2", node="reflector",
        template="Retry with a new generation candidate up to max_attempts=2 time(s).",
        docstring="Allow one retry beyond the default.",
        eval_task_ids=(), provenance={"parent": "reflector-default@v1", "generation": 1},
        version=2,
    )
    registry = SkillRegistry()
    first = _run("run_length_encoding_1", registry, reflector=mutated_reflector)
    assert first.solved
    assert not first.admission_attempts[0].admitted  # overfit still rejected

    second = _run("run_length_encoding_2", registry, reflector=mutated_reflector, generation=2)
    assert second.solved
    assert second.strategy == "generation"  # attempt 0 (overfit) fails on this task, attempt 1 (correct) wins
    assert second.admission_attempts[0].admitted  # general skill admitted this time
    assert len(registry) == 1

    heldout = _run("run_length_encoding_3", registry, reflector=mutated_reflector, generation=2)
    assert heldout.solved
    assert heldout.strategy == "skill_reuse"
