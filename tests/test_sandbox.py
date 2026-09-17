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


# --- hardening (docs/adr/0008) ----------------------------------------------

import sys  # noqa: E402

import pytest  # noqa: E402

from cambium.sandbox.runner import SandboxLimits, values_equal  # noqa: E402

POSIX = sys.platform != "win32"


def test_forged_ok_marker_does_not_pass():
    """Old harness trusted a printed marker; a candidate could print it and
    exit before any case ran."""
    src = (
        "import os\n"
        "print('__SANDBOX_OK__')\n"
        "os._exit(0)\n"
        "def add(a, b):\n"
        "    return 0\n"
    )
    r = run_in_sandbox(src, "add", [{"args": [1, 2], "expected": 3}])
    assert not r.ok


def test_always_equal_object_does_not_pass():
    src = (
        "class Anything:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def __ne__(self, other):\n"
        "        return False\n"
        "def add(a, b):\n"
        "    return Anything()\n"
    )
    r = run_in_sandbox(src, "add", [{"args": [1, 2], "expected": 3}])
    assert not r.ok
    assert "not JSON-serializable" in r.stderr


def test_child_never_sees_expected_values():
    src = (
        "import json\n"
        "def leak():\n"
        "    return open('cases.json').read()\n"
    )
    r = run_in_sandbox(src, "leak", [{"args": [], "expected": "SECRET-EXPECTED"}])
    assert not r.ok
    assert "SECRET-EXPECTED" not in r.stdout


def test_bool_is_not_accepted_for_int():
    assert not values_equal(True, 1)
    assert values_equal(1, 1.0)
    assert values_equal([1, {"a": [2]}], [1, {"a": [2]}])
    assert not values_equal([1, 2], [1, 2, 3])
    r = run_in_sandbox("def f():\n    return True", "f", [{"args": [], "expected": 1}])
    assert r.reason == "assertion_failed"


def test_tuple_return_matches_list_expected():
    r = run_in_sandbox("def f():\n    return (1, 2)", "f", [{"args": [], "expected": [1, 2]}])
    assert r.ok


def test_network_is_blocked():
    src = (
        "import socket\n"
        "def net():\n"
        "    s = socket.socket()\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "    return 1\n"
    )
    r = run_in_sandbox(src, "net", [{"args": [], "expected": 1}])
    assert not r.ok
    assert r.reason == "violation"
    assert "blocked socket" in r.stderr


def test_subprocess_is_blocked():
    src = "import subprocess\ndef run():\n    return subprocess.run(['echo', 'hi']).returncode\n"
    r = run_in_sandbox(src, "run", [{"args": [], "expected": 0}])
    assert r.reason == "violation"


def test_os_system_is_blocked():
    src = "import os\ndef run():\n    return os.system('echo hi')\n"
    r = run_in_sandbox(src, "run", [{"args": [], "expected": 0}])
    assert r.reason == "violation"


def test_ctypes_is_blocked():
    src = "def f():\n    import ctypes\n    return 1\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}])
    assert r.reason == "violation"


def test_write_outside_scratch_dir_is_blocked(tmp_path):
    target = tmp_path / "pwned.txt"
    src = f"def f():\n    open({str(target)!r}, 'w').write('x')\n    return 1\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}])
    assert r.reason == "violation"
    assert not target.exists()


def test_write_inside_scratch_dir_is_allowed():
    src = "def f():\n    open('scratch.txt', 'w').write('x')\n    return open('scratch.txt').read()\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": "x"}])
    assert r.ok


def test_violation_at_import_time_is_reported():
    src = "import socket\nsocket.getaddrinfo('example.com', 80)\ndef f():\n    return 1\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}])
    assert r.reason == "violation"


def test_common_stdlib_imports_still_work():
    src = (
        "import re, json, math, collections, itertools, functools, string, heapq, bisect\n"
        "def f(s):\n"
        "    return len(re.findall(r'[a-z]+', s))\n"
    )
    r = run_in_sandbox(src, "f", [{"args": ["a b c"], "expected": 3}])
    assert r.ok, r.stderr


def test_missing_function_is_an_exception():
    r = run_in_sandbox("def other():\n    return 1", "f", [{"args": [], "expected": 1}])
    assert r.reason == "exception"


def test_syntax_error_is_an_exception():
    r = run_in_sandbox("def f(:\n", "f", [{"args": [], "expected": 1}])
    assert r.reason == "exception"
    assert "SyntaxError" in r.stderr


def test_huge_output_is_truncated():
    src = "def f():\n    print('x' * 500000)\n    return 1\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}], limits=SandboxLimits(max_output_bytes=1000))
    assert r.ok
    assert len(r.stdout) < 1100
    assert "truncated" in r.stdout


@pytest.mark.skipif(not POSIX, reason="rlimits are POSIX-only")
def test_memory_limit_is_enforced():
    src = "def f():\n    x = bytearray(1024 * 1024 * 1024)\n    return len(x)\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}], limits=SandboxLimits(memory_mb=128))
    assert not r.ok
    assert r.reason == "resource_limit"


def test_environment_is_scrubbed(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret")
    src = "import os\ndef f():\n    return os.environ.get('GROQ_API_KEY', 'absent')\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": "absent"}])
    assert r.ok


def test_shutil_and_tempfile_imports_are_not_collateral_damage():
    src = "import shutil, tempfile\ndef f():\n    return 1\n"
    r = run_in_sandbox(src, "f", [{"args": [], "expected": 1}])
    assert r.ok, r.stderr
