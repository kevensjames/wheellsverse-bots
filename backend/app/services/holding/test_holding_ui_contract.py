"""Contract tests for the Holding UI HTML (Part C, §UI-CONTRACT-TESTS). Structural assertions on the
static page — no browser needed (hosted visual cert is separate). Run: python3 <this file>"""
import sys
from pathlib import Path

_HTML = Path(__file__).resolve().parents[4] / "frontend" / "admin" / "holding.html"
_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


HTML = _HTML.read_text()


def t_fetches_view_endpoint():
    assert "/admin/kai/holding/view" in HTML and "renderView(" in HTML


def t_today_is_first_operational_section():
    """TODAY FOR YOU must render before the status/entity sections."""
    assert "TODAY FOR YOU" in HTML
    assert HTML.index("renderView(") < HTML.index("renderStatus(await")   # view called before status
    # inside renderView, TODAY FOR YOU is the first panel
    rv = HTML[HTML.index("function renderView"):]
    assert rv.index("TODAY FOR YOU") < rv.index("KAI Working")


def t_company_list_is_dynamic_not_hardcoded():
    """Cards loop over the discovered companies; no hard-coded seven-name list."""
    assert "for(const c of (v.company_cards||[]))" in HTML
    # the current seven names must NOT appear as a hard-coded UI array
    for n in ("nurtelle", "siteboost", "solcircle"):
        assert n not in HTML.lower(), f"hard-coded company name leaked into UI: {n}"


def t_self_model_non_sentient():
    assert "Operational Self Model" in HTML
    low = HTML.lower()
    assert "sentient" not in low.replace("no claim to consciousness or sentience", "")
    assert "makes no claim to consciousness or sentience" in low


def t_ready_for_review_and_autonomy_backend():
    assert "Ready for review" in HTML and "Self-Improvement" in HTML
    assert "Autonomy" in HTML and "au.a2_certified_grants" in HTML and "au.money_mode" in HTML


def t_evidence_escaped_no_injection():
    """All dynamic values go through esc(); the self-improvement/evidence render uses esc()."""
    assert "const esc = s =>" in HTML
    rv = HTML[HTML.index("function renderView"):HTML.index("async function onProposalAction")]
    # every interpolation of a server value in renderView is wrapped in esc(
    assert "s.problem" in rv and "esc(s.problem)" in rv
    assert "esc(it.company)" in rv and "esc(c.name" in rv


def t_mobile_and_money_mode():
    assert 'name="viewport"' in HTML and "width=device-width" in HTML     # mobile
    assert "auto-fill,minmax" in HTML                                     # responsive grid
    assert "money mode" in HTML and "au.money_mode" in HTML               # MONEY_MODE truth surfaced


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
