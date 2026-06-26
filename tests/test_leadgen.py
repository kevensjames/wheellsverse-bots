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


def test_city_areas_cover_all_campaigns():
    assert set(leadgen._CITY_AREAS) == {c["slug"] for c in leadgen.CAMPAIGNS}
    for areas in leadgen._CITY_AREAS.values():
        assert len(areas) >= 3  # enough sub-areas to sweep a metro toward 100


def test_dedupe_key_is_stable_across_formatting():
    a = {"name": "Boston Dental", "phone": "(617) 555-0142"}
    b = {"name": "boston dental!!", "phone": "617-555-0142"}
    assert leadgen._dedupe_key(a) == leadgen._dedupe_key(b)


def test_reenrich_gated_on_key_and_scan(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    assert leadgen.reenrich("dental-boston")["status"] == "blocked"
    assert leadgen.reenrich("nope")["status"] == "unknown_campaign"
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    assert leadgen.reenrich("dental-boston")["status"] == "no_scan"  # nothing scanned yet
