"""dwolla — READ-ONLY inspection of the Dwolla (Sol ACH) account.

KAI can look up the connected account, customers, their bank funding sources,
and transfer status/history. It CANNOT move money: there is deliberately no
create/transfer action here. Money movement lives in
services/dwolla/operations.py behind @audited(destructive=True) + the
dwolla.transfer scope, invoked only by operator-approved admin actions — so no
prompt (or prompt-injection) routed through this tool can initiate a transfer.

Registered only when DWOLLA_KEY + DWOLLA_SECRET are set (inert otherwise).
"""
from __future__ import annotations

from typing import Any

from app.services.dwolla.client import DwollaClient, DwollaError
from app.services.tools.base import ToolContext, ToolError

_ACTIONS = {
    "account",            # the connected Dwolla account + capabilities
    "list_customers",     # customers (Sol members)
    "get_customer",       # one customer by id
    "list_funding_sources",  # a customer's linked bank accounts
    "list_transfers",     # transfers (optionally for one customer)
    "get_transfer",       # one transfer by id (status: pending/processed/failed)
}


class DwollaTool:
    name = "dwolla"
    description = (
        "Read-only inspection of the Sol payments (Dwolla ACH) account: view the "
        "connected account, list/get customers (circle members), list a customer's "
        "bank funding sources, and list/get ACH transfers with their status "
        "(pending/processed/failed/cancelled). Use when the operator asks about Sol "
        "payments, a member's bank link, or a transfer's status. This tool CANNOT "
        "move money — initiating transfers is an operator-approved action elsewhere."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_ACTIONS),
                "description": "Which read to perform.",
            },
            "customer_id": {
                "type": "string",
                "description": "Required for get_customer / list_funding_sources; "
                               "optional for list_transfers (scopes to that customer).",
            },
            "transfer_id": {"type": "string", "description": "Required for get_transfer."},
            "limit": {"type": "integer", "description": "list_*: default 25, max 200."},
        },
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            raise ToolError(f"action must be one of {sorted(_ACTIONS)}")

        try:
            client = DwollaClient()
        except DwollaError as e:
            raise ToolError(str(e))

        limit = int(kwargs.get("limit") or 25)

        try:
            if action == "account":
                acct = client.get_account()
                return {"action": action, "env": client.env, "account": acct,
                        "note": "Sol's connected Dwolla account. Report only fields present."}

            if action == "list_customers":
                data = client.list_customers(limit=limit)
                rows = (data.get("_embedded", {}) or {}).get("customers", [])
                return {"action": action, "env": client.env, "count": len(rows),
                        "customers": rows, "note": f"{len(rows)} Dwolla customer(s)."}

            if action == "get_customer":
                cid = _req(kwargs, "customer_id", action)
                return {"action": action, "env": client.env, "customer": client.get_customer(cid)}

            if action == "list_funding_sources":
                cid = _req(kwargs, "customer_id", action)
                data = client.list_funding_sources(cid)
                rows = (data.get("_embedded", {}) or {}).get("funding-sources", [])
                return {"action": action, "customer_id": cid, "count": len(rows),
                        "funding_sources": rows}

            if action == "list_transfers":
                cid = (kwargs.get("customer_id") or "").strip() or None
                data = client.list_transfers(customer_id=cid, limit=limit)
                rows = (data.get("_embedded", {}) or {}).get("transfers", [])
                return {"action": action, "customer_id": cid, "count": len(rows),
                        "transfers": rows, "note": "ACH status is authoritative only "
                        "after settlement; 'pending' can still fail/return later."}

            # get_transfer
            tid = _req(kwargs, "transfer_id", action)
            t = client.get_transfer(tid)
            return {"action": action, "transfer": t,
                    "status": t.get("status") if isinstance(t, dict) else None}
        except DwollaError as e:
            raise ToolError(str(e))


def _req(kwargs: dict, name: str, action: str) -> str:
    v = (kwargs.get(name) or "").strip()
    if not v:
        raise ToolError(f"{name} is required for action={action}")
    return v
