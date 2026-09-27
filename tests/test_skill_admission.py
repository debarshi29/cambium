from cambium.agent.generation import candidates_for
from cambium.agent.loop import build_skill_candidate
from cambium.skills.admission import admit_skill
from cambium.skills.registry import SkillRegistry
from cambium.tasks.pack import load_task_pack


def test_correct_skill_admitted_with_reuse_verified():
    pack = load_task_pack()
    origin = pack.by_id("fibonacci_1")
    source = candidates_for("fibonacci")[1].source  # correct
    candidate = build_skill_candidate(origin, source, generation=1)

    registry = SkillRegistry()
    result = admit_skill(candidate, registry, pack)

    assert result.admitted, result.detail
    assert result.reason == "admitted"
    assert registry.get_active("fibonacci_skill") is not None


def test_overfit_skill_rejected_on_reuse_check():
    """The flagship reward-hacking exhibit: passes its own origin task,
    fails the moment it has to generalize."""
    pack = load_task_pack()
    origin = pack.by_id("run_length_encoding_1")
    overfit_source = candidates_for("run_length_encoding")[0].source
    candidate = build_skill_candidate(origin, overfit_source, generation=1)

    registry = SkillRegistry()
    result = admit_skill(candidate, registry, pack)

    assert not result.admitted
    assert result.reason == "reuse_failed"
    assert registry.get_active("run_length_encoding_skill") is None


def test_broken_skill_rejected_at_sandbox_stage():
    pack = load_task_pack()
    origin = pack.by_id("fibonacci_1")
    flawed_source = candidates_for("fibonacci")[0].source  # fails its own cases
    candidate = build_skill_candidate(origin, flawed_source, generation=1)

    registry = SkillRegistry()
    result = admit_skill(candidate, registry, pack)

    assert not result.admitted
    assert result.reason == "sandbox_failed"


def test_duplicate_skill_rejected():
    pack = load_task_pack()
    origin = pack.by_id("fibonacci_1")
    source = candidates_for("fibonacci")[1].source
    candidate1 = build_skill_candidate(origin, source, generation=1)

    registry = SkillRegistry()
    first = admit_skill(candidate1, registry, pack)
    assert first.admitted

    other_train = pack.by_id("fibonacci_2")
    candidate2 = build_skill_candidate(other_train, source, generation=2)
    second = admit_skill(candidate2, registry, pack)
    assert not second.admitted
    assert second.reason == "duplicate"


def test_readmission_after_deprecation_becomes_the_next_version():
    """Regression: found by the curation stress test. Curation archives
    caesar_cipher_skill@v1, the loop re-solves the category and proposes a
    fresh caesar_cipher_skill (built as v1) -- which used to crash the
    registry with a version collision."""
    from cambium.agent.generation import candidates_for
    from cambium.agent.loop import build_skill_candidate
    from cambium.skills.admission import admit_skill
    from cambium.skills.registry import SkillRegistry
    from cambium.tasks.pack import load_task_pack

    pack = load_task_pack()
    origin = pack.by_id("caesar_cipher_1")
    source = candidates_for("caesar_cipher")[1].source
    registry = SkillRegistry()
    assert admit_skill(build_skill_candidate(origin, source, 1), registry, pack).admitted
    registry.deprecate("caesar_cipher_skill", 1, reason="size cap")

    result = admit_skill(build_skill_candidate(origin, source, 7), registry, pack)

    assert result.admitted
    versions = registry.all_versions("caesar_cipher_skill")
    assert [(v.version, v.deprecated) for v in versions] == [(1, True), (2, False)]
    assert registry.get_active("caesar_cipher_skill").provenance["generation"] == 7
