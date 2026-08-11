from cambium.prompts.admission import admit_prompt
from cambium.prompts.defaults import CRITIC_V1, PLANNER_V1, REFLECTOR_V1, seed_default_registry
from cambium.prompts.schema import Prompt
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()

REGRESSION_SUBSET = (
    "fibonacci_1", "primality_1", "gcd_lcm_1", "roman_numeral_1",
    "run_length_encoding_1", "caesar_cipher_1", "camel_snake_1",
)


def _mutated_reflector(max_attempts: int, version: int) -> Prompt:
    return Prompt(
        name=f"reflector-retry-{max_attempts}", node="reflector",
        template=f"Retry with a new generation candidate up to max_attempts={max_attempts} time(s).",
        docstring="Reflector retry-budget mutation.",
        eval_task_ids=REGRESSION_SUBSET,
        provenance={"parent": REFLECTOR_V1.key(), "generation": 1},
        version=version,
    )


def test_reflector_retry_budget_is_admitted_on_genuine_reuse():
    registry = seed_default_registry()
    candidate = _mutated_reflector(2, version=2)
    other_nodes = {"planner": PLANNER_V1, "critic": CRITIC_V1}

    result = admit_prompt(
        candidate, REFLECTOR_V1, other_nodes, REGRESSION_SUBSET, PACK,
        registry, SkillRegistry(), generation=1,
    )

    assert result.admitted, result
    assert result.candidate_rate > result.parent_rate
    assert len(result.gained_task_ids) >= 2
    assert registry.active("reflector").version == 2


def test_lateral_duplicate_reflector_variant_rejected_as_duplicate():
    registry = seed_default_registry()
    same_params = Prompt(
        name="reflector-relabeled", node="reflector",
        template="Retry with a new generation candidate up to max_attempts=1 time(s).",
        docstring="Same behavior, different name/docstring only.",
        eval_task_ids=REGRESSION_SUBSET,
        provenance={"parent": REFLECTOR_V1.key(), "generation": 1},
        version=2,
    )
    other_nodes = {"planner": PLANNER_V1, "critic": CRITIC_V1}

    result = admit_prompt(
        same_params, REFLECTOR_V1, other_nodes, REGRESSION_SUBSET, PACK,
        registry, SkillRegistry(), generation=1,
    )

    assert not result.admitted
    assert result.reason == "duplicate"


def test_planner_top_k_zero_regresses_and_is_rejected():
    """A pathological mutation (top_k=0 disables retrieval entirely) must
    never be admitted, even though it can't regress *this* regression
    subset (no skills exist yet to retrieve) -- pair it with a pre-seeded
    skill so the regression is real and demonstrable."""
    registry = seed_default_registry()
    base_skills = SkillRegistry()

    # Pre-admit a fibonacci skill via the normal path so retrieval has
    # something to find.
    mutated_reflector = _mutated_reflector(2, version=2)
    from cambium.agent.loop import run_task
    outcome = run_task(PACK.by_id("fibonacci_1"), 1, base_skills, PLANNER_V1, mutated_reflector, CRITIC_V1, PACK)
    assert outcome.solved and len(base_skills) == 1

    broken_planner = Prompt(
        name="planner-no-retrieval", node="planner",
        template="Retrieve the top_k=0 highest-scoring skills before attempting.",
        docstring="Pathological: disables retrieval entirely.",
        eval_task_ids=("fibonacci_2",),
        provenance={"parent": PLANNER_V1.key(), "generation": 1},
        version=2,
    )
    other_nodes = {"reflector": REFLECTOR_V1, "critic": CRITIC_V1}

    result = admit_prompt(
        broken_planner, PLANNER_V1, other_nodes, ("fibonacci_2",), PACK,
        registry, base_skills, generation=2,
    )

    assert not result.admitted
    assert result.reason in ("regression", "no_improvement")
