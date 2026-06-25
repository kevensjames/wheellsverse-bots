# tests/test_portfolio_html.py
from pathlib import Path

HTML = Path("frontend/admin/portfolio.html")


def test_dashboard_has_required_structure():
    text = HTML.read_text(encoding="utf-8")
    # injection hook + the four tab panels + the fetch wrapper
    assert "'%%API_KEY%%'" in text
    for marker in ['data-tab="overview"', 'data-tab="approvals"',
                   'data-tab="orchestrator"', 'data-tab="audit"']:
        assert marker in text, marker
    assert "/api/narai/portfolio/overview" in text
    assert "X-API-Key" in text
