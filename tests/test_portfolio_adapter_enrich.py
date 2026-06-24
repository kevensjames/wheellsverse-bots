from __future__ import annotations

import json

from core.portfolio.adapters.enrich import LeadsEnrichAdapter
from core.portfolio.actions import Action, ActionClass


def _action():
    return Action("enrich_leads", "email_enricher", ActionClass.GREEN, [], "n8n", {})


def test_enrich_writes_emails_back_onto_leads(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)        # force dry-run path
    # deterministic enrichment so the test asserts the WIRING, not the hash hit-rate
    import core.email_enricher as ee
    monkeypatch.setattr(ee, "_dry_run_enrich",
                        lambda p: {"email": p["name"].split()[0].lower() + "@found.example",
                                   "first_name": p["name"].split()[0]})
    leads = tmp_path / "n8n" / "artifacts" / "leads" / "prospects.json"
    leads.parent.mkdir(parents=True, exist_ok=True)
    leads.write_text(json.dumps([
        {"name": "Acme Plumbing", "website": "http://acme.example"},
        {"name": "Bob Cafe", "website": "http://bob.example"},
        {"name": "Already Has", "email": "set@already.example"},   # skipped (already has email)
    ]))
    res = LeadsEnrichAdapter().run(_action())
    assert res["dry_run"] is True
    assert res["total"] == 3
    assert res["enriched"] == 2                                  # the two without an email
    after = json.loads(leads.read_text())
    assert {p["name"]: p.get("email") for p in after} == {
        "Acme Plumbing": "acme@found.example",
        "Bob Cafe": "bob@found.example",
        "Already Has": "set@already.example",                    # untouched
    }


def test_enrich_empty_leads_is_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    res = LeadsEnrichAdapter().run(_action())                    # no leads file at all
    assert res["enriched"] == 0 and res["total"] == 0
