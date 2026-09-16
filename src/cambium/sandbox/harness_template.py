"""Child-process harness for cambium.sandbox.runner.

This file is *not* imported by cambium. Its text is copied into the
sandbox's scratch directory and run there as `python -I -S harness.py`,
alongside `candidate.py` (the code under test) and `cases.json` (call
arguments only -- never expected values; see runner.py).

Order of operations matters:
  1. read cases + candidate source while the filesystem is still trusted,
  2. apply POSIX resource limits,
  3. install an audit hook that cannot be removed for the rest of the
     process's life,
  4. only then exec the candidate and call it.

Everything the candidate can do happens after step 3.
"""
import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIMITS = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}


class SandboxViolation(PermissionError):
    pass


# Audit events refused outright: anything that reaches the network, spawns
# or signals a process, or loads native code.
_BLOCKED_PREFIXES = (
    "socket.",
    "subprocess.",
    "os.system",
    "os.exec",
    "os.spawn",
    "os.posix_spawn",
    "os.fork",
    "os.forkpty",
    "os.kill",
    "os.killpg",
    "os.startfile",
    "os.putenv",
    "os.unsetenv",
    "ctypes.",
    "_winapi.",
    "winreg.",
    "msvcrt.",
    "pty.",
    "webbrowser.",
    "urllib.Request",
    "http.client.",
    "ftplib.",
    "smtplib.",
    "poplib.",
    "imaplib.",
    "nntplib.",
    "telnetlib.",
    "sys.settrace",
    "sys.setprofile",
)

# Modules refused at import time. ctypes is also caught by the "ctypes."
# prefix above, but ctypes' own __getattr__ swallows that error into an
# AttributeError -- refusing the import gives a clean, reportable violation.
_BLOCKED_IMPORTS = frozenset({"ctypes", "_ctypes"})

# Audit events that mutate the filesystem: allowed inside the scratch dir,
# refused everywhere else. Value = indices of path arguments to check.
_PATH_EVENTS = {
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.rename": (0, 1),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.truncate": (0,),
    "os.symlink": (0, 1),
    "os.link": (0, 1),
    "os.utime": (0,),
    "shutil.rmtree": (0,),
    "shutil.copyfile": (1,),
    "shutil.move": (1,),
}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_in_hook = False


def _inside_scratch(path) -> bool:
    if isinstance(path, int):  # already-open file descriptor
        return True
    try:
        real = os.path.realpath(os.fsdecode(path))
    except (TypeError, ValueError):
        return False
    return real == _HERE or real.startswith(_HERE + os.sep)


def _is_write_open(mode, flags) -> bool:
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _audit(event, args):
    global _in_hook
    if _in_hook:
        return
    _in_hook = True
    try:
        if event.startswith(_BLOCKED_PREFIXES):
            raise SandboxViolation(f"sandbox: blocked {event}")
        if event == "import" and args and args[0] in _BLOCKED_IMPORTS:
            raise SandboxViolation(f"sandbox: blocked import of {args[0]}")
        if event == "open" and len(args) >= 3 and _is_write_open(args[1], args[2]):
            if not _inside_scratch(args[0]):
                raise SandboxViolation(f"sandbox: blocked write outside scratch dir: {args[0]!r}")
        idx = _PATH_EVENTS.get(event)
        if idx is not None:
            for i in idx:
                if i < len(args) and not _inside_scratch(args[i]):
                    raise SandboxViolation(f"sandbox: blocked {event} outside scratch dir: {args[i]!r}")
    finally:
        _in_hook = False


def _apply_rlimits():
    try:
        import resource
    except ImportError:  # Windows: no rlimits; the timeout is the only bound
        return
    mem = _LIMITS.get("memory_bytes")
    cpu = _LIMITS.get("cpu_seconds")
    fsize = _LIMITS.get("file_size_bytes")
    for name, value in (("RLIMIT_AS", mem), ("RLIMIT_CPU", cpu), ("RLIMIT_FSIZE", fsize)):
        if value is None or not hasattr(resource, name):
            continue
        try:
            resource.setrlimit(getattr(resource, name), (int(value), int(value)))
        except (ValueError, OSError):
            pass  # e.g. RLIMIT_AS is not enforceable on macOS


def _write_result(payload):
    path = os.path.join(_HERE, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _error_payload(exc):
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:2000],
        "violation": isinstance(exc, SandboxViolation),
        "memory": isinstance(exc, MemoryError),
    }


def main():
    with open(os.path.join(_HERE, "cases.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    with open(os.path.join(_HERE, "candidate.py"), encoding="utf-8") as fh:
        source = fh.read()
    fn_name = spec["fn_name"]
    cases = spec["cases"]

    _apply_rlimits()
    sys.addaudithook(_audit)

    results = []
    try:
        namespace = {"__name__": "__candidate__", "__builtins__": __builtins__}
        exec(compile(source, "candidate.py", "exec"), namespace)
        fn = namespace[fn_name]
    except BaseException as exc:  # noqa: BLE001 -- report anything, incl. SystemExit
        traceback.print_exc()
        _write_result({"load_error": _error_payload(exc), "results": results})
        return

    for case in cases:
        try:
            got = fn(*case.get("args", []), **case.get("kwargs", {}))
        except BaseException as exc:  # noqa: BLE001
            traceback.print_exc()
            results.append({"error": _error_payload(exc)})
            break
        try:
            # Only plain JSON crosses back to the parent, so a returned
            # object can't smuggle a custom __eq__ into the comparison.
            results.append({"value": json.loads(json.dumps(got))})
        except (TypeError, ValueError) as exc:
            results.append({"error": {
                "type": "UnserializableResult",
                "message": f"return value of type {type(got).__name__} is not JSON-serializable: {exc}",
                "violation": False,
                "memory": False,
            }})
            break
    _write_result({"results": results})


if __name__ == "__main__":
    main()
