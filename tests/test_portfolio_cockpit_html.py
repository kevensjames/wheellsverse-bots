from pathlib import Path
def test_cockpit_html_structure():
    t = Path("frontend/admin/portfolio_cockpit.html").read_text(encoding="utf-8")
    assert "/api/narai/portfolio/biz/" in t
    for m in ['data-tab="overview"', 'data-tab="build"', 'data-tab="artifacts"', 'data-tab="audit"']:
        assert m in t
    # served behind the owner session: same-origin calls with its cookie, no key
    assert "credentials:'same-origin'" in t
    assert "%%API_KEY%%" not in t and "X-API-Key" not in t
    assert "location.pathname" in t
