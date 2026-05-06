"""Local pytest fixtures for ``infra/brain/tests/debug/``.

The shared parent ``conftest.py`` autouses ``_isolate_chroma`` and
``_isolate_default_registry`` — both import the brain runtime modules
(``infra.brain.memory``, ``infra.brain.tools``) which in turn pull
``chromadb``. These tests do not exercise either subsystem; they cover
the pure-Python ``ci_auto_fix`` / ``repair_generator`` path. The
overrides below short-circuit those fixtures so tests can run in
environments without ChromaDB / litellm installed.

Pytest fixture inheritance: defining a fixture with the same name in a
deeper conftest replaces the parent fixture's behaviour for everything
under that directory, while leaving the rest of the suite untouched.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_chroma():
    """Override the parent fixture — no chroma touch needed for these tests."""
    yield


@pytest.fixture(autouse=True)
def _isolate_default_registry():
    """Override the parent fixture — these tests don't register any tools."""
    yield
