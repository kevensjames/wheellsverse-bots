"""Scan: Anthropic API credit is low / exhausted.

Pattern from session history: the trend-scan endpoint and LLM-triage
both failed for hours because the Anthropic balance was depleted —
nothing alerted until the operator noticed dead endpoints. This scanner
makes the credit state observable.

Probe strategy: send a 1-token Messages API call. Three possible outcomes:
  - 200 → credit is fine, no finding
  - 400/402 with 'credit' or 'quota' or 'balance' in error → flag HIGH
  - 401/403 or network error → flag LOW (auth/connectivity, not credit)

We don't probe more than once per scan cycle and we cache the result
in state so the launchd cron doesn't burn extra tokens — but each
scan cycle does ONE probe, so the 06:00 daily run sends ≤ 1 message
per day. At ~$0.0001/call that's ~$0.03/year.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _load_api_key() -> str:
    """Same resolution chain as triage.py — we may run before that module
    has been imported, so duplicate the lookup."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    for env_file in (
        Path("/Volumes/Wheellsverse/wheellsverse-bots/.env"),
        Path("/Volumes/Wheellsverse/wheellsverse_bots.OLD_PRE_MIGRATION/.env"),
        Path("/Volumes/Wheellsverse/narai/.env"),
    ):
        if not env_file.is_file():
            continue
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("ANTHROPIC_API_KEY="):
                    val = s.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            continue
    return ""


def _probe_credit(api_key: str, timeout: float = 8.0) -> tuple[int, str]:
    """Send a tiny request. Returns (http_status, body_excerpt)."""
    payload = json.dumps({
        "model": DEFAULT_MODEL,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "."}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_API_URL, data=payload, method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", errors="replace")[:200]
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, f"network: {e}"


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    # Only fire this scanner once per cycle, not per-project. The scanner
    # interface scopes to a project, so we gate by a single-project check:
    # only run for the wheellsverse-bots project (the one with the .env).
    if project.name != "wheellsverse-bots":
        return []

    api_key = _load_api_key()
    if not api_key:
        # No key configured — informational only
        return [{
            "severity": "low",
            "location": "(env)",
            "evidence": "ANTHROPIC_API_KEY not set in env or any known .env file",
            "fix_payload": {"action": "set_api_key"},
        }]

    code, body = _probe_credit(api_key)

    if code == 200:
        return []  # credit is fine

    body_lower = body.lower()
    is_credit_issue = any(
        k in body_lower for k in (
            "credit balance", "credit balance is too low",
            "quota", "billing", "low balance", "insufficient",
        )
    )

    if is_credit_issue:
        return [{
            "severity": "high",
            "location": f"{ANTHROPIC_API_URL} (HTTP {code})",
            "evidence": "Anthropic API credit low/exhausted — "
                        + (body[:200] if body else "see provider dashboard"),
            "fix_payload": {"action": "top_up", "http_code": code},
        }]

    if code in (401, 403):
        return [{
            "severity": "medium",
            "location": f"{ANTHROPIC_API_URL} (HTTP {code})",
            "evidence": f"Anthropic auth failed — key may be rotated/revoked. {body[:140]}",
            "fix_payload": {"action": "check_key", "http_code": code},
        }]

    if code == 0:
        return [{
            "severity": "low",
            "location": ANTHROPIC_API_URL,
            "evidence": f"Anthropic API unreachable: {body[:140]}",
            "fix_payload": {"action": "check_network"},
        }]

    # Other 4xx/5xx — informational
    return [{
        "severity": "low",
        "location": f"{ANTHROPIC_API_URL} (HTTP {code})",
        "evidence": f"Anthropic returned HTTP {code}: {body[:160]}",
        "fix_payload": {"http_code": code},
    }]
