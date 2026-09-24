import os

import pytest

from cambium.sandbox.cache import CachingBackend
from cambium.sandbox.runner import SubprocessBackend, set_default_backend

# One memoizing backend shared by the whole test session (per xdist worker):
# the eval-harness tests re-run the same scripted candidates against the
# same tasks hundreds of times, and the verdicts are deterministic. When CI
# selects another tier explicitly (CAMBIUM_SANDBOX=docker), respect it and
# don't cache, so that job really exercises the container every time.
_SESSION_BACKEND = None if os.environ.get("CAMBIUM_SANDBOX") else CachingBackend(SubprocessBackend())


@pytest.fixture(autouse=True)
def _fresh_sandbox_backend():
    """Each test starts from the session backend (or, under an explicit
    CAMBIUM_SANDBOX, from its own environment), so a test that swaps the
    default never leaks into the next one."""
    set_default_backend(_SESSION_BACKEND)
    yield
    set_default_backend(_SESSION_BACKEND)
