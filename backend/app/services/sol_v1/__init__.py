"""Sol v1 — non-custodial ROSCA coordinator service layer.

Separate namespace from the legacy custodial ``app.services.sol`` (Dwolla).
Sol v1 never touches money: it coordinates and records member-to-member
payments made outside the app.
"""
from app.services.sol_v1 import lifecycle

__all__ = ["lifecycle"]
