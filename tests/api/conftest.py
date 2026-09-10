"""
tests/api/conftest.py
─────────────────────────────────────────────────────────────────────────────
Shared fixtures for NarAI API tests.

Sets a valid JWT secret before the auth module is imported, preventing the
fail-fast validation from blocking test execution.
"""

import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def _set_test_jwt_secret():
    """Set a valid JWT secret for all tests in this directory.

    The auth module validates NARAI_JWT_SECRET at import time and exits if
    it's missing or insecure. This fixture runs before any test imports the
    auth module, ensuring tests can run without requiring developers to set
    the environment variable manually.
    """
    if "NARAI_JWT_SECRET" not in os.environ:
        # Use a test-specific secret that meets security requirements:
        # - Not in _INSECURE_DEFAULTS
        # - At least 32 characters long
        os.environ["NARAI_JWT_SECRET"] = (
            "test-secret-for-narai-api-tests-minimum-32-chars"
        )
