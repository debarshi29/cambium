"""End-to-end curation under growth pressure (docs/adr/0011). A short run
of the same scenario scripts/run_curation_stress.py runs for 25
generations."""
import pytest

from cambium.eval.stress import BOOTSTRAP_GENERATIONS, StressConfig, run_stress
from cambium.tasks.pack import load_task_pack

PACK = load_task_pack()
GENS = 8
CAP = 22


@pytest.fixture(scope="module")
def curated():
    return run_stress(PACK, StressConfig(generations=GENS, variants_per_generation=4,
                                         max_active_skills=CAP))


@pytest.fixture(scope="module")
def uncurated():
    return run_stress(PACK, StressConfig(generations=GENS, variants_per_generation=4, curation=False))


def test_noisy_variants_get_through_the_gate(uncurated):
    """The proposer's variants are correct, so the gate admits them -- the
    pressure on curation is real, not simulated by bypassing admission."""
    assert all(r.admitted == 4 for r in uncurated.records)


def test_uncurated_library_grows_without_bound(uncurated):
    sizes = [r.active_skills for r in uncurated.records]
    assert sizes == sorted(sizes)
    assert sizes[-1] == 17 + 4 * GENS


def test_curated_library_stays_bounded(curated):
    for r in curated.records:
        if r.generation % 2 == 0:  # right after a curation pass
            assert r.active_skills <= CAP
    assert max(r.active_skills for r in curated.records) < 17 + 4 * GENS


def test_curation_archives_rather_than_deletes(curated):
    last = curated.records[-1]
    assert last.total_versions >= 17 + 4 * GENS
    assert last.total_versions > last.active_skills
    assert sum(last.deprecated_by_reason.values()) == last.total_versions - last.active_skills


def test_curation_never_drops_a_capability(curated):
    """Coverage-aware curation: every category that had a skill before the
    stress run still has one, and held-out stays solved after every pass."""
    categories = {s.provenance["category"] for s in curated.skill_registry.active()}
    assert len(categories) == 17
    for r in curated.records:
        if r.generation % 2 == 0:
            assert r.heldout_solved == r.heldout_total


def test_curated_retrieval_beats_uncurated(curated, uncurated):
    assert curated.records[-1].recall_at_k > uncurated.records[-1].recall_at_k


def test_generations_continue_after_bootstrap(curated):
    assert curated.records[0].generation == BOOTSTRAP_GENERATIONS + 1
    assert len(curated.records) == GENS
