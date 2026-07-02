import pytest
from factory import budget, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def test_default_ceilings():
    c = budget.load_ceilings()
    assert c.per_project_month == 100.0 and c.portfolio_month == 500.0


def test_ceilings_from_file():
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 10, "portfolio_month": 25}})
    c = budget.load_ceilings()
    assert c.per_project_month == 10.0 and c.portfolio_month == 25.0


def test_spent_sums_by_month_and_slug():
    budget.record_spend("a", 3.0, "step", "2026-06")
    budget.record_spend("a", 2.0, "step", "2026-06")
    budget.record_spend("b", 5.0, "step", "2026-06")
    budget.record_spend("a", 9.0, "step", "2026-07")
    assert budget.spent("2026-06", "a") == 5.0
    assert budget.spent("2026-06") == 10.0


def test_would_exceed_per_project():
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 10, "portfolio_month": 100}})
    budget.record_spend("a", 9.0, "step", "2026-06")
    assert budget.would_exceed("a", 2.0, "2026-06") is True
    assert budget.would_exceed("a", 0.5, "2026-06") is False


def test_would_exceed_portfolio():
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 1000, "portfolio_month": 10}})
    budget.record_spend("a", 6.0, "step", "2026-06")
    budget.record_spend("b", 3.0, "step", "2026-06")
    assert budget.would_exceed("a", 2.0, "2026-06") is True
