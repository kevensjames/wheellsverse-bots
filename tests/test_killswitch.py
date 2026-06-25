from core.portfolio import killswitch, budget


def test_no_spend_is_dormant_not_failing(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = killswitch.assess("2026-06")
    # nothing spent anywhere -> all dormant, ZERO false pause-flags
    assert a["pause_candidates"] == []
    assert len(a["dormant"]) == 10
    assert all(r["status"] == "dormant" for r in a["businesses"])


def test_spend_without_return_is_pause_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    budget.record_spend("n8n", 25.0, "llm", "2026-06")   # burned money, $0 back
    a = killswitch.assess("2026-06", threshold=1.0)
    n8n = next(r for r in a["businesses"] if r["slug"] == "n8n")
    assert n8n["status"] == "pause_candidate"
    assert n8n["roi"] == 0.0
    assert "n8n" in a["pause_candidates"]
    assert a["auto_paused"] == []                          # recommend-only
