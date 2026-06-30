import pytest
from factory import report, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def _cycle():
    return {"cycle_id": "c1", "slug": "acme", "task_id": "t1", "status": "completed",
            "stages": [{"verb": "implement", "status": "executed", "detail": "executed"},
                       {"verb": "deploy_staging", "status": "queued", "detail": "queued"}],
            "pr_url": "https://gh/pr/1", "cost_usd": 0.42, "at": "2026-06-30T02:00:00Z"}


def test_render_includes_status_pr_and_cost():
    md = report.render_report(_cycle())
    assert "acme" in md and "completed" in md
    assert "https://gh/pr/1" in md
    assert "0.42" in md
    assert "implement" in md and "deploy_staging" in md


def test_render_handles_no_pr():
    c = _cycle()
    c["pr_url"] = None
    md = report.render_report(c)
    assert "no pr" in md.lower()


def test_write_report_creates_file():
    p = report.write_report("acme", _cycle(), date="2026-06-30")
    assert p == paths.project_dir("acme") / "reports" / "2026-06-30.md"
    assert "completed" in p.read_text(encoding="utf-8")
