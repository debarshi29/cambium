import pytest

from cambium.sandbox.runner import set_default_backend


@pytest.fixture(autouse=True)
def _fresh_sandbox_backend():
    """Each test resolves the sandbox backend from its own environment
    (CAMBIUM_SANDBOX), so a monkeypatched env never leaks across tests."""
    set_default_backend(None)
    yield
    set_default_backend(None)
