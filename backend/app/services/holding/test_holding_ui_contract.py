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
# The data fetches moved out of boot() into loadAll() so they can RE-RUN when the owner signs in through the
# orb — before that, the 401 panels rendered at page load stayed on screen until a manual reload, which reads
# as "signed in, still broken". The contract is unchanged (one /view fetch powers every aggregate section),
# so BOOT now slices from loadAll(); boot() itself is asserted separately to still drive it.
BOOT = HTML[HTML.index("function loadAll()"):]


def _fn(name, end="\n}\n"):
    """Body of a top-level JS function (from its `function name(` to the next `\\n}\\n`)."""
    i = HTML.index("function " + name + "(")
    return HTML[i:HTML.index(end, i)]


def t_fetches_view_endpoint():
    """The page fetches /view once and renders every aggregate-powered section from it."""
    assert "api('/admin/kai/holding/view')" in BOOT
    for r in ("renderToday(v)", "renderWorking(v)", "renderProblems(v)", "renderAutonomy(v)", "renderSelfModel(v)"):
        assert r in BOOT, f"loadAll() does not render {r} from the /view payload"


def t_panels_refresh_on_sign_in():
    """Signing in through the orb must re-fetch — not leave the 401 panels up until a manual reload.

    The page necessarily loads before the operator has a session, so the first pass renders NOT_CONNECTED
    on every panel. Without this the operator signs in, sees 'OWNER · GOVERNED' on the orb, and still reads
    'HTTP 401' on every card.
    """
    boot = _fn("boot")
    assert "loadAll()" in boot, "boot() must drive the data load"
    assert "refreshAuthBanner()" in boot, "boot() must render the auth banner"
    assert "KAI.on('principal'" in boot, "boot() must subscribe to the presence principal event"
    assert "loadAll()" in boot[boot.index("KAI.on('principal'"):], "the principal handler must re-run loadAll()"
    assert "kai:ready" in boot, "must fall back to kai:ready when the presence layer has not mounted yet"
    # the subscribe path must not throw when the presence layer lacks the API
    assert "typeof window.KAI.on === 'function'" in boot, "the subscription must be feature-guarded"
    # and the banner must no longer instruct a manual reload
    assert "then reload" not in HTML, "the banner should not tell the operator to reload"


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


def t_stale_backend_contract_banner():
    """C5: a 200 from an older backend must raise ONE page-level banner, not silent per-panel 'unavailable'."""
    assert 'id="contractbar"' in HTML, "no page-level contract banner element"
    cv = _fn("checkViewContract")
    # required keys are tested for PRESENCE (an empty list / UNAVAILABLE marker is a compatible answer)
    assert "VIEW_CONTRACT_KEYS.filter(k => !(k in v))" in cv
    for k in ("health", "attention", "timeline", "missions", "system_model"):
        assert "'" + k + "'" in HTML[HTML.index("const VIEW_CONTRACT_KEYS"):HTML.index("function checkViewContract")]
    # transport failures stay the per-panel NOT_CONNECTED story; only a 200 can trip this banner
    assert "if(failed(v)" in cv
    # the banner names the missing keys and never invents a version/semver
    assert "esc(missing.join(', '))" in cv
    assert not re.search(r"v\d+\.\d+\.\d+", cv), "fabricated version string in the contract banner"
    assert "checkViewContract(v)" in BOOT, "boot() never runs the contract check"


def t_signin_guidance_is_actionable_on_this_page():
    """C7: the banner must point at this page's presence orb (which mints the owner cookie), not elsewhere."""
    # whoami + the banner moved into refreshAuthBanner() so sign-in can re-render them without a reload.
    boot_auth = _fn("refreshAuthBanner")
    assert "/admin/session/whoami" in boot_auth
    assert "KAI orb" in boot_auth and "bottom-right" in boot_auth
    assert "Command Center" not in boot_auth, "sign-in guidance still sends the operator to another page"
    assert "window.KAI.open()" in boot_auth, "the call-to-action does not open the presence drawer"
    # the rendered banner never carries a credential, key or token (comments may name the mechanism)
    shown = boot_auth[boot_auth.index("bar.innerHTML='Owner"):boot_auth.index("addEventListener")]
    for bad in ("x-api-key", "api_key", "apikey", "secret", "token", "password"):
        assert bad not in shown.lower(), f"credential material in the rendered sign-in banner: {bad}"


def t_timeline_empty_is_never_ambiguous():
    """§61: an empty Timeline must say WHY. 'no events recorded' and 'no source is readable' are different
    facts and must not share a message — otherwise the operator reads an unwired panel as 'nothing
    happened'. (The rendered text of each state is asserted in frontend/admin/test_timeline_panel.js.)"""
    rt = _fn("renderTimeline")
    assert "tl.store" in rt and "s.status === 'CONNECTED'" in rt, "the panel ignores store/source status"
    assert "does NOT mean nothing happened" in rt, "no explicit unavailable state for unreadable sources"
    assert "No observable events recorded by the connected sources" in rt, "no honest-empty state"
    # the two states are mutually exclusive branches of one condition, never the same string
    assert "tl.store !== 'CONNECTED' || !live.length" in rt
    # and nothing is ever rendered that did not come from the payload's stored events
    assert "for(const e of evs)" in rt and "arr(tl.events)" in rt


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
