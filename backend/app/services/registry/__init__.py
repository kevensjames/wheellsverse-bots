"""WHEELLSVERSE canonical registry — the single source of truth for the Command Center.

Pure stdlib (no FastAPI import at module load) so it is testable with `python3`
and importable from core.api without pulling the web stack. The registry carries
STRUCTURAL truth only (what exists, where, its honest deploy state, its admin
route) — it never fabricates health, revenue, or live metrics. Live values come
from real probes the UI calls (e.g. /api/health, /admin/capabilities.json); where
no probe exists the value is UNAVAILABLE, never a guess.
"""
from .catalog import (
    registry_snapshot, systems, companies, Node,
    DeployState, Status, DataClass, CANONICAL_IDS,
)

__all__ = [
    "registry_snapshot", "systems", "companies", "Node",
    "DeployState", "Status", "DataClass", "CANONICAL_IDS",
]
