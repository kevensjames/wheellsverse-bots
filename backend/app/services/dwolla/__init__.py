"""Dwolla — the ACH money-movement rail for Sol (ROSCA savings circles).

KAI talks to Dwolla over HTTPS; it never runs Dwolla code. This package is the
client + the governed money-movement operations. Safety is layered:

  1. The LLM-facing `dwolla` tool (services/tools/dwolla_tool.py) is READ-ONLY —
     it can inspect accounts/customers/funding-sources/transfers but cannot move
     money, so no prompt (or prompt-injection) can initiate a transfer.
  2. Money-movement ops here are @audited(destructive=True) — they raise
     PendingApproval unless called with approved=True (an operator action).
  3. Scope KAI_SCOPE_DWOLLA* is off by default — even an approved call is denied
     until the operator opts in.
  4. The client is SANDBOX-LOCKED — it refuses the production host unless
     DWOLLA_ALLOW_PRODUCTION=1 is explicitly set.

Configure via .env: DWOLLA_ENV (sandbox|production), DWOLLA_KEY, DWOLLA_SECRET,
DWOLLA_WEBHOOK_SECRET (for verifying inbound webhooks).
"""
from app.services.dwolla.client import (
    DwollaClient,
    DwollaError,
    DwollaProductionLocked,
    verify_webhook,
)

__all__ = [
    "DwollaClient",
    "DwollaError",
    "DwollaProductionLocked",
    "verify_webhook",
]
