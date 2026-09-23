import pytest

from cambium.tasks.pack import load_task_pack


def test_pack_loads_and_splits():
    pack = load_task_pack()
    assert len(pack.tasks) == 60
    assert len(pack.train) == 40
    assert len(pack.heldout) == 20


def test_no_duplicate_ids():
    pack = load_task_pack()
    ids = [t.id for t in pack.tasks]
    assert len(ids) == len(set(ids))


def test_every_category_has_at_least_two_tasks_for_reuse():
    pack = load_task_pack()
    from collections import Counter
    counts = Counter(t.category for t in pack.tasks)
    assert all(n >= 2 for n in counts.values()), counts


def test_other_task_in_category_excludes_self():
    pack = load_task_pack()
    task = pack.by_id("fibonacci_1")
    other = pack.other_task_in_category(task)
    assert other is not None
    assert other.id != task.id
    assert other.category == task.category


def test_skill_categories_have_two_train_tasks_for_admission_reuse_check():
    """The admission gate's reuse check (CLAUDE.md §3.2 condition 4) must never
    touch held-out tasks. Every category that needs a skill synthesized (i.e.
    not a base capability) needs >=2 train tasks so origin + reuse both stay
    in-train. See docs/adr/0003-scaled-demo.md."""
    pack = load_task_pack()
    base_categories = {"string_reverse", "word_count", "palindrome_check"}
    from collections import Counter
    train_counts = Counter(t.category for t in pack.train)
    for category, count in train_counts.items():
        if category not in base_categories:
            assert count >= 2, f"{category} has only {count} train task(s)"


def test_by_id_missing_raises():
    pack = load_task_pack()
    with pytest.raises(KeyError):
        pack.by_id("does_not_exist")


def test_full_spec_shape_every_category_is_two_train_one_heldout():
    """CLAUDE.md §4: 40 train / 20 held-out. docs/adr/0010: 20 categories x
    (2 train + 1 held-out), base-capability categories included."""
    from collections import Counter
    pack = load_task_pack()
    train = Counter(t.category for t in pack.train)
    heldout = Counter(t.category for t in pack.heldout)
    assert len(train) == 20
    assert set(train) == set(heldout)
    assert all(n == 2 for n in train.values()), train
    assert all(n == 1 for n in heldout.values()), heldout


def test_every_generation_category_has_ground_truth_for_every_task():
    from cambium.agent.generation import CANDIDATE_BANK
    from cambium.retrieval.recall import load_ground_truth
    pack = load_task_pack()
    gt = load_ground_truth()
    for task in pack.tasks:
        if task.category in CANDIDATE_BANK:
            assert gt.get(task.id) == f"{task.category}_skill", task.id
    assert set(gt) <= {t.id for t in pack.tasks}
