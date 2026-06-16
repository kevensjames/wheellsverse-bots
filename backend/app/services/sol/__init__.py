"""Sol — ROSCA (rotating savings circle) ledger + engine.

storage.py  — SQLite ledger (circles/members/cycles/contributions/payouts).
engine.py   — pure ROSCA state machine over the ledger (no money movement).

Money movement (Dwolla ACH) is orchestrated by the audited Sol admin endpoints,
which call app.services.dwolla.operations and feed transfer results back via the
engine's mark_* functions. See app/routers/sol.py.
"""
from app.services.sol import engine, storage

__all__ = ["engine", "storage"]
