from __future__ import annotations

import json

from core.portfolio.adapters.outreach_send import OutreachSendAdapter
from core.portfolio.actions import Action, ActionClass


def _action():
    return Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {})


def test_no_recipients_when_leads_have_no_email(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    leads = tmp_path / "n8n" / "artifacts" / "leads" / "prospects.json"
    leads.parent.mkdir(parents=True, exist_ok=True)
    leads.write_text(json.dumps([{"name": "Acme Plumbing"}]))   # no email
    res = OutreachSendAdapter().run(_action())
    assert res["status"] == "no_recipients"


def test_real_gated_send_is_dry_run_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # a lead WITH an email (simulating enrichment / an operator-supplied list)
    leads = tmp_path / "n8n" / "artifacts" / "leads" / "prospects.json"
    leads.parent.mkdir(parents=True, exist_ok=True)
    leads.write_text(json.dumps([{"name": "Acme Plumbing", "email": "owner@acme.example"}]))
    res = OutreachSendAdapter().run(_action())
    # it composed a real recipient and called SiteBoost's REAL engine, which
    # BLOCKS by default (no --confirm) — proving it's wired + gated, not a stub.
    assert res["recipients"] == 1
    assert res["armed"] is False and res["live"] is False
    assert res["status"] == "blocked"
    assert "confirm" in res["send_result"]["reason"].lower()
