"""twenty_crm — read/write a Twenty CRM instance (people, companies,
opportunities) via its REST API.

Native KAI tool: KAI talks to YOUR self-hosted Twenty over HTTP — it does NOT
run any Twenty code. Configure with TWENTY_API_URL (your instance root, e.g.
https://crm.example.com) + TWENTY_API_KEY (Settings → Developers → API key).
Registered only when both are set, so it's inert until you point it at a CRM.

REST shape (Twenty v0.x): GET/POST {url}/rest/{object}, Bearer auth, results
wrapped in {"data": {...}}. Parsing is defensive so minor schema drift degrades
to "raw" rather than crashing. stdlib-only, fail-soft.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_OBJECTS = {"people", "companies", "opportunities", "notes", "tasks"}
_SINGULAR = {
    "people": "person", "companies": "company", "opportunities": "opportunity",
    "notes": "note", "tasks": "task",
}
_ACTIONS = {"list", "get", "create"}
_TIMEOUT = 20


class TwentyCrmTool:
    name = "twenty_crm"
    description = (
        "Read/write a Twenty CRM: list or search people, companies, and "
        "opportunities (deals), fetch one by id, or create a record. Use when "
        "the operator asks about CRM contacts, accounts, or pipeline. Requires "
        "a configured Twenty instance."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "create"],
                "description": "list/search records, get one by id, or create one.",
            },
            "object": {
                "type": "string",
                "enum": sorted(_OBJECTS),
                "description": "Which CRM object to operate on.",
            },
            "record_id": {"type": "string", "description": "Required for action=get."},
            "search": {"type": "string", "description": "Optional text filter for action=list."},
            "limit": {"type": "integer", "description": "list: default 20, max 100."},
            "data": {
                "type": "object",
                "description": "Record fields for action=create (Twenty's schema, e.g. "
                               "{'name': {'firstName': 'Ada', 'lastName': 'Lovelace'}}).",
            },
        },
        "required": ["action", "object"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        base = (os.environ.get("TWENTY_API_URL") or "").strip().rstrip("/")
        key = (os.environ.get("TWENTY_API_KEY") or "").strip()
        if not base or not key:
            raise ToolError("Twenty is not configured — set TWENTY_API_URL + TWENTY_API_KEY")

        action = (kwargs.get("action") or "").strip().lower()
        obj = (kwargs.get("object") or "").strip().lower()
        if action not in _ACTIONS:
            raise ToolError(f"action must be one of {sorted(_ACTIONS)}")
        if obj not in _OBJECTS:
            raise ToolError(f"object must be one of {sorted(_OBJECTS)}")

        if action == "list":
            n = max(1, min(int(kwargs.get("limit") or 20), 100))
            params = {"limit": n}
            search = (kwargs.get("search") or "").strip()
            if search:
                params["search"] = search
            url = f"{base}/rest/{obj}?{urllib.parse.urlencode(params)}"
            data = self._request("GET", url, key)
            records = self._extract(data, obj)
            return {"action": "list", "object": obj, "count": len(records),
                    "results": records, "note": f"Twenty: {len(records)} {obj}."}

        if action == "get":
            rid = (kwargs.get("record_id") or "").strip()
            if not rid:
                raise ToolError("record_id is required for action=get")
            url = f"{base}/rest/{obj}/{urllib.parse.quote(rid)}"
            data = self._request("GET", url, key)
            return {"action": "get", "object": obj, "record": self._extract(data, obj),
                    "note": f"Twenty: fetched {obj} {rid}."}

        # create
        body = kwargs.get("data")
        if not isinstance(body, dict) or not body:
            raise ToolError("data (object) is required for action=create")
        url = f"{base}/rest/{obj}"
        data = self._request("POST", url, key, body=body)
        return {"action": "create", "object": obj, "record": self._extract(data, obj),
                "note": f"Twenty: created a {_SINGULAR.get(obj, obj)}."}

    @staticmethod
    def _request(method: str, url: str, key: str, body: dict | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:
                pass
            raise ToolError(f"Twenty API {e.code}: {detail or e.reason}")
        except Exception as e:
            raise ToolError(f"Twenty request failed: {e}")

    @staticmethod
    def _extract(data: dict[str, Any], obj: str) -> Any:
        """Twenty wraps results in data.<object> (list) or data.<singular>.
        Defensive: fall back to the raw data so schema drift never crashes."""
        d = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(d, dict):
            if obj in d:
                return d[obj]
            singular = _SINGULAR.get(obj, obj[:-1] if obj.endswith("s") else obj)
            if singular in d:
                return d[singular]
        return d
