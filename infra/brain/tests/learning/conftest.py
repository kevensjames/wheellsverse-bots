"""Local pytest fixtures for ``infra/brain/tests/learning/``.

Same pattern as ``tests/debug/conftest.py`` — overrides the parent
``_isolate_chroma`` and ``_isolate_default_registry`` autouse fixtures
with no-ops so this slice runs in environments without ChromaDB /
litellm installed (the chromadb venv blocker logged in
``project_brain_test_venv`` memory).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_chroma():
    yield


@pytest.fixture(autouse=True)
def _isolate_default_registry():
    yield
