"""Outreach send adapter — REAL, gated send via SiteBoost's own cold_outreach engine.

This is the piece that makes the n8n pilot "work like SiteBoost": it composes a
cold_outreach-compatible sequences file from the business's leads and fires it
through `core.cold_outreach.send_sequences` — the *same* engine SiteBoost uses,
with the *same* triple-gate (confirm + live + safe-domain + Instantly keys).

Default is DRY-RUN: it returns cold_outreach's honest "blocked" result until the
operator arms it via the per-business flags `outreach_armed` (→ confirm) and
`outreach_live` (→ live), exactly as SiteBoost requires --confirm --live. Building
this does NOT send; sending requires deliberate arming + real Instantly creds.

Honest gap: prospects from the lead scanner have no email until enriched, so a
business with un-enriched leads returns `no_recipients` (the same prerequisite
SiteBoost solves with its email-enrichment step) rather than pretending to send.
"""
from __future__ import annotations

import os
import time

from core.portfolio import paths, state

DAILY_CAP = 50


def compose_sequences_file(business: str):
    """Build a cold_outreach sequences file from this business's lead artifact.
    Returns (path, n_recipients). Only prospects WITH an email become recipients.
    """
    leads_path = paths.business_dir(business) / "artifacts" / "leads" / "prospects.json"
    prospects = paths.load_json(leads_path, []) or []
    domain = os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com").strip()
    seqs = []
    for p in prospects:
        if not isinstance(p, dict):
            continue
        email = (p.get("email") or "").strip()
        if not email:
            continue
        name = p.get("name") or "there"
        seqs.append({
            "to_email": email, "to_name": name, "business_name": name, "skipped": False,
            "touches": [
                {"day": 0, "subject": f"Quick automation idea for {name}",
                 "body": (f"Hi {name}, I help teams automate repetitive workflows with n8n — "
                          f"usually a few hours a week back. Worth a 10-minute look?\n\n"
                          f"Unsubscribe: https://{domain}/u")},
                {"day": 3, "subject": f"Re: automation for {name}",
                 "body": (f"Following up — I can map 2-3 workflows to automate for {name} on a quick call.\n\n"
                          f"Unsubscribe: https://{domain}/u")},
                {"day": 7, "subject": "Last note",
                 "body": (f"No worries if now isn't the time — happy to share a free workflow template either way.\n\n"
                          f"Unsubscribe: https://{domain}/u")},
            ],
        })
    out = paths.business_dir(business) / "artifacts" / "outreach" / "sequences.json"
    paths.save_json_atomic(out, {
        "_meta": {"outbound_domain": domain, "sender_name": "Jay",
                  "composed_at": time.strftime("%Y-%m-%d", time.gmtime()),
                  "n_sequences": len(seqs)},
        "sequences": seqs,
    })
    return out, len(seqs)


class OutreachSendAdapter:
    def __init__(self, generate=None):
        self._generate = generate

    def run(self, action) -> dict:
        business = action.business
        path, n = compose_sequences_file(business)
        if n == 0:
            return {"status": "no_recipients", "verb": action.verb,
                    "note": ("Leads have no email addresses — enrichment is required before send "
                             "(the same prerequisite SiteBoost solves via its enrichment step)."),
                    "sequences_file": str(path)}
        # SiteBoost-parity gated send. Default dry-run; operator arms via flags.
        armed = state.get_flag(business, "outreach_armed", False)
        live = state.get_flag(business, "outreach_live", False)
        from core import cold_outreach
        result = cold_outreach.send_sequences(path, confirm=armed, live=live, max_per_day=DAILY_CAP)
        return {"status": result.get("status"), "verb": action.verb,
                "recipients": n, "armed": armed, "live": live,
                "send_result": result, "sequences_file": str(path)}
