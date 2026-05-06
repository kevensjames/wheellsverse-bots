"""Local pytest fixtures for ``infra/brain/tests/debug/``.

The shared parent ``conftest.py`` autouses ``_isolate_chroma`` and
``_isolate_default_registry`` — both import the brain runtime modules
(``infra.brain.memory``, ``infra.brain.tools``) which in turn pull
``chromadb``. These tests do not exercise either subsystem; they cover
the pure-Python ``ci_auto_fix`` / ``repair_generator`` path AND, as of
Phase G.2, the ``BrainClient`` init path (which transitively imports
``infra.brain.memory`` so chromadb has to resolve at all).

The overrides below short-circuit the autouse fixtures so tests can
run in environments without ChromaDB / litellm installed. The
``sys.modules`` stubs at the bottom let the ``BrainClient`` test file
collect cleanly — ``import chromadb`` inside ``infra.brain.memory``
gets a mock that's never called by these specific tests.

Pytest fixture inheritance: defining a fixture with the same name in a
deeper conftest replaces the parent fixture's behaviour for everything
under that directory, while leaving the rest of the suite untouched.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


# ── Module stubs (run at conftest import, before any test collection) ──
#
# Phase G.2 added a test that needs to import :class:`BrainClient`,
# which transitively triggers ``import chromadb`` in
# ``infra.brain.memory``. The local ``.venv-1`` doesn't have chromadb
# (the canonical "next-phase TODO" in
# ``project_brain_test_venv.md`` memory). Stub it before pytest tries
# to import the test module so collection succeeds.
#
# These stubs are inert — they only matter as the result of
# ``import chromadb`` at module load. The Phase G tests never call
# Chroma functions (they hand-construct ``RepairOutcomeStore`` against
# a tmp_path JSONL file).

def _stub_module(name: str) -> MagicMock:
    """Install a MagicMock at ``sys.modules[name]`` if not already
    present, returning the live reference. The ``__path__`` attr lets
    Python treat the stub as a package, so ``from <name>.<sub> import …``
    statements can also pull a stubbed submodule."""
    existing = sys.modules.get(name)
    if existing is not None and not isinstance(existing, MagicMock):
        # Real module installed — leave it alone.
        return existing
    stub = MagicMock(name=f"stub.{name}")
    stub.__path__ = []  # marks it as a package for from-import purposes
    sys.modules[name] = stub
    return stub


# Top-level stubs.
for _missing_dep in ("chromadb", "litellm"):
    _stub_module(_missing_dep)

# Submodules consumed by ``infra.brain.memory`` — Python's import
# machinery hits ``sys.modules['chromadb.utils']`` when resolving
# ``from chromadb.utils import …``, so we need to register the
# submodule explicitly even though the parent stub exists.
for _submodule in ("chromadb.utils",):
    _stub_module(_submodule)


@pytest.fixture(autouse=True)
def _isolate_chroma():
    """Override the parent fixture — no chroma touch needed for these tests."""
    yield


@pytest.fixture(autouse=True)
def _isolate_default_registry():
    """Override the parent fixture — these tests don't register any tools."""
    yield
