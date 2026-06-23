from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.leads import LeadsAdapter
from core.portfolio.actions import Action, ActionClass


def test_leads_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    import core.places_scanner as ps

    class _P:
        def __init__(self):
            self.__dict__ = {"name": "Acme", "website": "", "place_id": "x"}

    monkeypatch.setattr(ps, "scan", lambda **kw: [_P(), _P()])
    res = LeadsAdapter().run(Action("generate_lead_list", "places_scanner", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and "Acme" in p.read_text()
    assert res["count"] == 2
