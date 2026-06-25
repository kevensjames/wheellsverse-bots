from core.portfolio import budget, paths


def test_default_ceilings(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    c = budget.load_ceilings()
    assert c.per_business_month == 100.0
    assert c.portfolio_month == 500.0


def test_record_and_sum_spend(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    budget.record_spend("n8n", 10.0, "deploy", "2026-06")
    budget.record_spend("n8n", 5.0, "llm", "2026-06")
    budget.record_spend("ghost", 7.0, "deploy", "2026-06")
    budget.record_spend("n8n", 99.0, "deploy", "2026-07")  # different month
    assert budget.spent("2026-06") == 22.0
    assert budget.spent("2026-06", "n8n") == 15.0


def test_would_exceed_per_business_ceiling(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    budget.record_spend("n8n", 95.0, "deploy", "2026-06")
    assert budget.would_exceed("n8n", 10.0, "2026-06") is True   # 105 > 100
    assert budget.would_exceed("n8n", 4.0, "2026-06") is False    # 99 <= 100


def test_would_exceed_portfolio_ceiling(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # Five businesses each at 90 = 450 portfolio; ceiling 500.
    for slug in ["a", "b", "c", "d", "e"]:
        budget.record_spend(slug, 90.0, "deploy", "2026-06")
    # New business 'f' adding 60 -> portfolio 510 > 500, even though 60 < per-business 100.
    assert budget.would_exceed("f", 60.0, "2026-06") is True
    assert budget.would_exceed("f", 40.0, "2026-06") is False    # 490 <= 500
