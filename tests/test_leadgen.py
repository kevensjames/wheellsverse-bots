from pathlib import Path

from core.portfolio import leadgen


def test_six_campaigns():
    cs = leadgen.list_campaigns()
    assert len(cs) == 6
    assert {c["slug"] for c in cs} == {
        "dental-boston", "pi-lawyers-miami", "hvac-houston",
        "roofing-phoenix", "chiro-dallas", "realestate-atlanta"}


def test_credential_status_is_honest(monkeypatch):
    for k in ("GOOGLE_PLACES_API_KEY", "HUNTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cs = leadgen.credential_status()
    assert cs["google_places"] is False and cs["hunter"] is False


def test_run_campaign_dryrun_flagged_and_writes_crm(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    for k in ("GOOGLE_PLACES_API_KEY", "HUNTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    r = leadgen.run_campaign("dental-boston")
    # no creds -> explicitly NOT real, dry-run flagged (never passed off as real)
    assert r["is_real"] is False
    assert r["dry_run_scan"] is True and r["dry_run_enrich"] is True
    assert r["total_leads_found"] >= 0
    assert "next_actions" in r and any("GOOGLE_PLACES_API_KEY" in a for a in r["next_actions"])
    # CRM import file written + has a header
    crm = Path(r["artifacts"]["crm_csv"])
    assert crm.exists()
    assert crm.read_text().splitlines()[0].startswith("name,email,contact_name")


def test_unknown_campaign_is_handled(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert leadgen.run_campaign("does-not-exist")["status"] == "unknown_campaign"
