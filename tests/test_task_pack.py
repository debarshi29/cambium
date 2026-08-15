from cambium.tasks.pack import load_task_pack


def test_pack_loads_and_splits():
    pack = load_task_pack()
    assert len(pack.tasks) == 20
    assert len(pack.train) == 14
    assert len(pack.heldout) == 6


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


def test_by_id_missing_raises():
    pack = load_task_pack()
    try:
        pack.by_id("does_not_exist")
        assert False, "expected KeyError"
    except KeyError:
        pass
