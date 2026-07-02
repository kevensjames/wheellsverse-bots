from pathlib import Path
def test_cockpit_html_structure():
    t = Path("frontend/admin/portfolio_cockpit.html").read_text(encoding="utf-8")
    assert "'%%API_KEY%%'" in t
    assert "/api/narai/portfolio/biz/" in t
    for m in ['data-tab="overview"', 'data-tab="build"', 'data-tab="artifacts"', 'data-tab="audit"']:
        assert m in t
    assert "X-API-Key" in t
    assert "location.pathname" in t
