from cambium.agent.generation import candidates_for
from cambium.agent.loop import build_skill_candidate
from cambium.eval.scoring import retrieval_or_base_solved, score_tasks
from cambium.prompts.defaults import PLANNER_V1
from cambium.prompts.schema import Prompt
from cambium.skills.admission import admit_skill
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()


def test_base_capability_solved_without_any_skills():
    registry = SkillRegistry()
    task = PACK.by_id("string_reverse_2")  # heldout, base capability
    assert retrieval_or_base_solved(task, registry, PLANNER_V1)


def test_skill_requiring_heldout_task_unsolved_with_empty_registry():
    registry = SkillRegistry()
    task = PACK.by_id("fibonacci_3")  # heldout, needs a skill
    assert not retrieval_or_base_solved(task, registry, PLANNER_V1)


def test_skill_requiring_heldout_task_solved_once_skill_admitted():
    registry = SkillRegistry()
    origin = PACK.by_id("fibonacci_1")
    source = candidates_for("fibonacci")[1].source
    result = admit_skill(build_skill_candidate(origin, source, generation=1), registry, PACK)
    assert result.admitted

    task = PACK.by_id("fibonacci_3")
    assert retrieval_or_base_solved(task, registry, PLANNER_V1)


def test_never_falls_back_to_generation():
    """The whole point of this scorer: a category with a generation bank
    but no admitted skill and no base capability must NOT be solved, even
    though cambium.agent.loop would solve it via fresh generation."""
    registry = SkillRegistry()
    task = PACK.by_id("caesar_cipher_3")
    assert not retrieval_or_base_solved(task, registry, PLANNER_V1)


def test_top_k_zero_disables_retrieval_entirely():
    registry = SkillRegistry()
    origin = PACK.by_id("fibonacci_1")
    source = candidates_for("fibonacci")[1].source
    admit_skill(build_skill_candidate(origin, source, generation=1), registry, PACK)

    zero_k_planner = Prompt(
        name="p", node="planner", template="top_k=0", docstring="d",
        eval_task_ids=(), provenance={"parent": None, "generation": 0},
    )
    assert not retrieval_or_base_solved(PACK.by_id("fibonacci_3"), registry, zero_k_planner)


def test_score_tasks_returns_per_task_bool_map():
    registry = SkillRegistry()
    scores = score_tasks(("string_reverse_2", "fibonacci_3"), registry, PLANNER_V1, PACK)
    assert scores == {"string_reverse_2": True, "fibonacci_3": False}
