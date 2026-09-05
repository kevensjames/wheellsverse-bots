"""Contract tests for the Holding UI HTML (Part C, §UI-CONTRACT-TESTS). Structural assertions on the
static page — no browser needed (hosted visual cert is separate). Run: python3 <this file>

Re-pinned after Phase 6b-2 (§148 command-center rewrite): the page now fetches /view once in boot()
and fans out to per-section render* functions. The semantics below are unchanged; only identifiers moved."""
import re
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
BOOT = HTML[HTML.index("function boot()"):]


def _fn(name, end="\n}\n"):
    """Body of a top-level JS function (from its `function name(` to the next `\\n}\\n`)."""
    i = HTML.index("function " + name + "(")
    return HTML[i:HTML.index(end, i)]


def t_fetches_view_endpoint():
    """boot() fetches /view once and renders every aggregate-powered section from it."""
    assert "api('/admin/kai/holding/view')" in BOOT
    for r in ("renderToday(v)", "renderWorking(v)", "renderProblems(v)", "renderAutonomy(v)", "renderSelfModel(v)"):
        assert r in BOOT, f"boot() does not render {r} from the /view payload"


def t_today_is_first_operational_section():
    """TODAY FOR YOU must render before the status/entity sections."""
    low = HTML.lower()
    assert "today for you" in low
    # first <section> in <main> is the TODAY panel
    main = HTML[HTML.index("<main"):]
    assert 'id="p-today"' in main[:main.index("</section>")], "first section in <main> is not TODAY FOR YOU"
    # markup order: TODAY panel before KAI Working panel
    assert HTML.index('id="h-today"') < HTML.index('id="h-work"')
    # render order in boot(): today first, before working / status-ish sections
    assert BOOT.index("renderToday(v)") < BOOT.index("renderWorking(v)")
    assert BOOT.index("renderToday(v)") < BOOT.index("renderWorkers")


def t_company_list_is_dynamic_not_hardcoded():
    """Cards loop over the discovered companies; no hard-coded seven-name list."""
    rc = _fn("renderCompanies")
    assert "arr(ov.entities)" in rc and "for(const e of ents)" in rc
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
    rw = _fn("renderWorking")
    assert "v.self_improvement_ready" in rw and ".ready_for_review" in rw   # surfaced from the payload
    ra = _fn("renderAutonomy")
    assert "Autonomy" in HTML and "a.a2_certified_grants" in ra and "a.money_mode" in ra


def t_evidence_escaped_no_injection():
    """All dynamic values go through esc(); the self-improvement/evidence/problem renders use esc()."""
    assert "const esc = s =>" in HTML
    rw = _fn("renderWorking")
    assert "s.problem" in rw and "esc(s.problem)" in rw and "esc(it.company)" in rw
    rp = _fn("renderProblems")
    assert "esc(p.company)" in rp and "esc(p.observed_facts" in rp
    assert "esc(e.brand)" in _fn("renderCompanies")
    # no template-literal interpolation anywhere (all server data is concatenated through esc())
    assert "${" not in HTML
    # every per-item server field interpolated as HTML in a render* function is esc()-wrapped
    # (numbers via .length / Math.round and String(bool) are the only bare values allowed)
    bare = re.findall(r"\+\s*(?!esc\(|badge\(|sevChip\(|conf\(|fmtTs\(|evBtn\(|metric\(|honest\(|emptyMsg\(|arr\([^)]*\)\.length|String\(!!|String\([^)]*===|Math\.|cell\(|regSearch\()"
                      r"([a-z]{1,3}\.[a-z_]+(?:\.[a-z_]+)*)\s*\+", HTML[HTML.index("function renderToday"):HTML.index("function boot()")])
    bare = [b for b in bare if not b.endswith(".length")]          # array counts are numbers, not markup
    assert not bare, f"un-escaped server field(s) interpolated into HTML: {sorted(set(bare))}"


def t_mobile_and_money_mode():
    assert 'name="viewport"' in HTML and "width=device-width" in HTML     # mobile
    assert "auto-fill,minmax" in HTML                                     # responsive grid
    assert "money mode" in HTML and "a.money_mode" in _fn("renderAutonomy")   # MONEY_MODE truth surfaced


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
