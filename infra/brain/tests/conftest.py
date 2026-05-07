"""Shared pytest fixtures for the brain test suite.

These fixtures isolate every test from disk and from the network:

  * The chroma collection used by ``memory.recall`` / ``rag.query`` is
    swapped for an in-memory mock — tests never touch ``narai/data/chroma``.
    Tests that exercise the real ChromaDB pipeline opt out with
    ``@pytest.mark.real_chroma`` (or a module-level
    ``pytestmark = pytest.mark.real_chroma``).
  * The litellm router is patched per-test as needed; the ``router_mock``
    fixture provides the boilerplate.
  * The default tool registry is snapshotted before each test and restored
    after, so tests that register fixtures don't leak into each other.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make the repo root importable regardless of where pytest is invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pytest_configure(config):
    """Register the markers we use so pytest doesn't warn about them."""
    config.addinivalue_line(
        "markers",
        "real_chroma: opt out of the chroma-mocking fixture and use real ChromaDB",
    )


# ── Chroma isolation ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_chroma(request, monkeypatch, tmp_path):
    """Replace the chroma collections with mocks for the duration of a test.

    Every test gets a fresh, empty pair (memory + rag). Tests that need
    populated collections override the ``count``/``query`` methods on the
    fixtures returned below.

    Tests carrying the ``real_chroma`` marker skip the mocking entirely
    and instead get an isolated, on-disk Chroma instance under ``tmp_path``
    via the ``NARAI_CHROMA_PATH`` env var. Module-level singletons are
    reset around the test so collections don't leak across files.
    """
    if request.node.get_closest_marker("real_chroma"):
        # Real-chroma path: per-test temp dir, reset the module singletons.
        monkeypatch.setenv("NARAI_CHROMA_PATH", str(tmp_path / "chroma"))
        import infra.brain.memory as _mem
        import infra.brain.rag as _rag
        _mem._client = None
        _mem._collection = None
        _rag._rag_collection = None
        yield
        _mem._client = None
        _mem._collection = None
        _rag._rag_collection = None
        return

    fake_mem_col = MagicMock(name="mem_col")
    fake_mem_col.count.return_value = 0
    fake_mem_col.query.return_value = {
        "documents": [[]], "metadatas": [[]], "distances": [[]],
    }
    fake_rag_col = MagicMock(name="rag_col")
    fake_rag_col.count.return_value = 0
    fake_rag_col.query.return_value = {
        "documents": [[]], "metadatas": [[]], "distances": [[]],
    }
    import infra.brain.memory as _mem
    import infra.brain.rag as _rag
    monkeypatch.setattr(_mem, "_get_collection", lambda: fake_mem_col)
    monkeypatch.setattr(_rag, "_get_rag_collection", lambda: fake_rag_col)
    yield


# ── Tool registry isolation ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_default_registry(monkeypatch):
    """Snapshot + restore the default ToolRegistry around each test."""
    from infra.brain.tools import default_registry
    reg = default_registry()
    snapshot = dict(reg._tools)
    yield
    # Restore: drop anything new + replace anything mutated.
    reg._tools.clear()
    reg._tools.update(snapshot)


# ── Router-mock helper ──────────────────────────────────────────────────────


def make_router_response(content: str, tokens: int = 11):
    r = MagicMock()
    r.choices[0].message.content = content
    r.usage.total_tokens = tokens
    return r


@pytest.fixture
def router_mock(monkeypatch):
    """Return an AsyncMock patched onto litellm.acompletion.

    Tests set ``router_mock.return_value = make_router_response("...")`` for
    a single response, or ``router_mock.side_effect = [resp1, resp2, ...]``
    for a scripted sequence.
    """
    mock = AsyncMock()
    monkeypatch.setattr(
        "infra.brain.router.litellm.acompletion", mock
    )
    return mock


# ── Convenience BrainClient fixtures ────────────────────────────────────────


@pytest.fixture
def narai_client():
    """Fresh NarAI-mode BrainClient with default registry + telemetry on."""
    from infra.brain.interface import BrainClient
    return BrainClient(user_id="owner", mode="narai")


@pytest.fixture
def nai_client():
    """Fresh NAI-mode BrainClient (restricted tools, telemetry on)."""
    from infra.brain.interface import BrainClient
    return BrainClient(user_id="alice", mode="nai")


@pytest.fixture
def permissive_client():
    """Fresh BrainClient with an unrestricted custom policy.

    Pre-Phase-B (audit Critical Issue #1) ``narai_client`` was unrestricted;
    many tests of executor/run_task *mechanics* relied on that to register
    arbitrary tool names. After Phase B, NarAI is a true allowlist
    (``allowed_tools=("web_search",)``), so those tests use this fixture
    instead. Tests that exercise the *policy gate itself* keep using
    ``narai_client`` / ``nai_client``.
    """
    from infra.brain.interface import BrainClient, BrainPolicy
    return BrainClient(
        user_id="owner",
        policy=BrainPolicy(
            mode="test_permissive",
            tone="test",
            system_prompt="test",
            memory_enabled=False,
            rag_enabled=False,
            tools_enabled=True,
            allowed_tools=None,             # unrestricted by name
            allowed_capabilities=None,      # capability gate off
        ),
    )
