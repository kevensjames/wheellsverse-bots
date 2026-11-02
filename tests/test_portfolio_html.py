# tests/test_portfolio_html.py
from pathlib import Path

HTML = Path("frontend/admin/portfolio.html")


def test_dashboard_has_required_structure():
    text = HTML.read_text(encoding="utf-8")
    # the four tab panels + the fetch wrapper
    for marker in ['data-tab="overview"', 'data-tab="approvals"',
                   'data-tab="orchestrator"', 'data-tab="audit"']:
        assert marker in text, marker
    assert "/api/narai/portfolio/overview" in text
    # served behind the owner session: same-origin calls with its cookie, no key
    assert "credentials:'same-origin'" in text
    assert "%%API_KEY%%" not in text and "X-API-Key" not in text
