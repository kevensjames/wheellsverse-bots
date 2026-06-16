"""Governed Dwolla money-movement operations.

Every function here is @audited — it records to the audit log, requires its
scope to be enabled (KAI_SCOPE_DWOLLA*), and the money-moving one requires
explicit approval. These are NOT exposed to the LLM tool; they're called by
operator-driven admin endpoints (or scripts) where `approved=True` is supplied
by a deliberate human action.

Scopes (all off by default — opt in per .env):
    dwolla.customer   — create/verify customers           (destructive=False)
    dwolla.funding    — attach bank funding sources        (destructive=False)
    dwolla.transfer   — initiate ACH transfers (MONEY!)    (destructive=True)
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.dwolla.client import DwollaClient
from app.services.governance import audited

logger = logging.getLogger(__name__)


@audited(scope="dwolla.customer", destructive=False)
def create_customer(customer: dict[str, Any]) -> dict[str, Any]:
    """Create a Dwolla Customer (one per Sol circle member). Not money movement,
    but still scoped + audited because it creates a real (sandbox) financial
    identity tied to PII."""
    res = DwollaClient().create_customer(customer)
    return {"ok": True, "location": res.get("location"), "raw": res}


@audited(scope="dwolla.funding", destructive=False)
def add_funding_source(customer_id: str, source: dict[str, Any]) -> dict[str, Any]:
    """Attach a bank account to a customer (typically {plaidToken, name})."""
    res = DwollaClient().create_funding_source(customer_id, source)
    return {"ok": True, "location": res.get("location"), "raw": res}


@audited(scope="dwolla.transfer", destructive=True)
def initiate_transfer(source_href: str, dest_href: str, value: str,
                      currency: str = "USD", metadata: dict | None = None) -> dict[str, Any]:
    """Move money via ACH. DESTRUCTIVE — requires approved=True (stripped by the
    @audited decorator before this body runs) AND the dwolla.transfer scope.

    For Sol: source = member funding source / pool balance, dest = pool balance /
    recipient funding source, value = "200.00" (contribution) or "3600.00" (payout).
    """
    client = DwollaClient()
    res = client.create_transfer(source_href, dest_href, value, currency=currency, metadata=metadata)
    location = res.get("location")
    logger.info("dwolla: transfer initiated %s -> %s (%s %s) loc=%s",
                source_href, dest_href, value, currency, location)
    return {"ok": True, "transfer_url": location, "raw": res}
