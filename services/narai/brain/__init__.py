"""NarAI brain — public API surface.

Real implementation at ``backend/app/services/nai_brain/``. This shim
preserves the locked Stage 0 namespace ``services.narai.brain`` so the
consumer face (Stage 4) can import from a stable path.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.nai_brain.memory_injection import (  # noqa: E402
    DEFAULT_INJECT_K,
    build_memory_preamble,
)

__all__ = ["DEFAULT_INJECT_K", "build_memory_preamble"]
