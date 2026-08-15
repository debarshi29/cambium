from cambium.sandbox.runner import run_in_sandbox


def test_passing_source_ok():
    r = run_in_sandbox("def add(a, b):\n    return a + b", "add", [{"args": [1, 2], "expected": 3}])
    assert r.ok
    assert r.reason == "ok"


def test_wrong_output_fails_assertion():
    r = run_in_sandbox("def add(a, b):\n    return a + b", "add", [{"args": [1, 2], "expected": 999}])
    assert not r.ok
    assert r.reason == "assertion_failed"


def test_raising_source_is_exception():
    r = run_in_sandbox("def boom():\n    raise ValueError('nope')", "boom", [{"args": [], "expected": None}])
    assert not r.ok
    assert r.reason == "exception"


def test_slow_source_times_out():
    src = "def slow():\n    import time\n    time.sleep(10)"
    r = run_in_sandbox(src, "slow", [{"args": [], "expected": None}], timeout=0.5)
    assert not r.ok
    assert r.reason == "timeout"


def test_multiple_cases_all_checked():
    src = "def square(n):\n    return n * n"
    cases = [{"args": [2], "expected": 4}, {"args": [3], "expected": 10}]  # second is wrong
    r = run_in_sandbox(src, "square", cases)
    assert not r.ok
    assert "case 1" in r.stderr
