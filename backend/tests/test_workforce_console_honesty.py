"""Phase 5A — static honesty/security checks on the DARK Angular console SOURCE.

Runnable now (pure Python, no Angular toolchain): scans the committed Angular
source for any network or execution pattern, and asserts the console is inert by
construction — no HttpClient/fetch/WebSocket/etc., no enabled action, the canonical
NOT-AVAILABLE label present, every governed action disabled with no event output.
The governed sandbox's `ng test`/`ng build` is the later, separate gate.

Hardened per the Phase-5A review: comment stripping is HTML-aware and does not
reach inside backtick template literals; the forbidden-token and action-verb sets
match the full contract threat model; `.scss` is scanned for CSS egress.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "frontend-pilots" / "kai-angular" / "src"
_APP = _SRC / "app"
LABEL = "NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED"

# The generated data modules are pure `WorkforceData`/`WorkforceMeta` literals (no
# executable code); their contents are arbitrary upstream strings (role names, file
# paths like "...-navigator.md") that would false-match code patterns. They are
# verified instead by their structural checks below and by
# test_workforce_ui_export's byte-match to a fresh catalog export. The code-pattern
# scan therefore runs over HAND-WRITTEN code only.
_GENERATED = {"workforce-data.ts", "workforce-meta.ts"}
_TS_HTML = sorted([*_APP.rglob("*.ts"), *_APP.rglob("*.html")])
_CODE = [p for p in _TS_HTML if p.name not in _GENERATED]
_SCSS = sorted([*_SRC.rglob("*.scss")])


def _strip_comments(path: Path) -> str:
    """Remove comments so prose can't false-match, WITHOUT reaching into code that
    must stay scannable. HTML: strip `<!-- -->` only. TS: strip `/* */`, then strip
    `//` line comments ONLY outside backtick template literals (so a token inside a
    component's inline template is still scanned)."""
    src = path.read_text()
    if path.suffix == ".html":
        return re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    parts = src.split("`")  # even indices are OUTSIDE template literals
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"//[^\n]*", " ", parts[i])
    return "`".join(parts)


# network / execution / storage primitives that must not appear in console CODE.
# (dynamic local `import(...)` for lazy route code-split is standard Angular and
# NOT forbidden.)
_FORBIDDEN_CODE = (
    "@angular/common/http", "HttpClient", "provideHttpClient", "HttpClientModule",
    "fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "axios",
    "eval(", "Function(", "localStorage", "sessionStorage", "document.cookie",
    "navigator.", "window.open", ".postMessage(", "new Image(",
    "location.href", "location.assign", "location.replace", "window.location",
    'src="http', "src='http", 'href="http', "href='http",
    # CSS network egress reachable from inline component `styles: [...]` blocks
    # (the .scss scan only covers separate .scss files):
    "url(", "http://", "https://",
)
# execution/lifecycle verbs that must not be invoked by a (click)/action handler.
_ACTION_VERBS = (
    "execute", "dispatch", "activate", "assign", "run", "deploy", "spawn", "enable",
    "migrate", "invoke", "launch", "start", "submit", "trigger", "perform", "send",
    "publish", "provision", "fire", "admit", "approve", "bind", "mount",
)


@pytest.mark.parametrize("path", _CODE, ids=lambda p: p.name)
def test_no_network_or_execution_primitive(path):
    code = _strip_comments(path)
    for tok in _FORBIDDEN_CODE:
        assert tok not in code, f"{path.name} references {tok!r} (console must be inert/offline)"


@pytest.mark.parametrize("path", _SCSS, ids=lambda p: p.name)
def test_scss_has_no_network_egress(path):
    css = re.sub(r"/\*.*?\*/", " ", path.read_text(), flags=re.S)
    for tok in ("url(", "@import", "http://", "https://"):
        assert tok not in css, f"{path.name} references {tok!r} (CSS network egress forbidden)"


def test_no_event_handler_invokes_an_action_verb():
    # Scan EVERY Angular event binding (click)/(change)/(submit)/(ngSubmit)/(keyup)/…
    # not just (click), and both quote styles. `[(ngModel)]` two-way bindings are not
    # matched (their ')' is followed by ']' not '=').
    for path in _CODE:
        for m in re.finditer(r"\(([a-zA-Z][\w.]*)\)=([\"'])(.*?)\2", path.read_text()):
            body = m.group(3).lower()
            assert not any(v in body for v in _ACTION_VERBS), \
                f"{path.name}: ({m.group(1)}) handler {m.group(3)!r} invokes an action verb"


def test_canonical_label_present_in_action_control_and_shell():
    ga = (_APP / "workforce" / "governed-action.component.ts").read_text()
    shell = (_APP / "app.component.html").read_text()
    assert LABEL in ga
    assert LABEL in shell


_BARE_DISABLED = r"(?<![-\w])disabled(?![-\w=])"  # a bare `disabled`, not `aria-disabled`/`disabled=`


def test_governed_action_is_always_disabled_with_no_output():
    ga = (_APP / "workforce" / "governed-action.component.ts").read_text()
    # The <button> ELEMENT itself must carry a real bare `disabled` attribute — not
    # merely advisory `aria-disabled`, and not just the word "disabled" appearing in
    # a doc comment (which a raw file scan would wrongly accept).
    btn = re.search(r"<button\b[^>]*>", ga, re.S)
    assert btn, "governed-action must render a <button>"
    assert re.search(_BARE_DISABLED, btn.group(0)), "the <button> must carry a bare disabled attribute"
    assert "(click)" not in ga                    # no click handler at all
    assert "@Output" not in ga and "EventEmitter" not in ga  # cannot emit an action


def test_disabled_check_rejects_comment_only_mention():
    # Teeth: a button with ONLY aria-disabled must fail the guard even if a comment
    # says "disabled" — proving the check anchors to the element, not file prose.
    fake = ('/** always a disabled control. Rendered disabled. */ '
            '@Component({ template: `<button type="button" aria-disabled="true">x</button>` })')
    btn = re.search(r"<button\b[^>]*>", fake, re.S)
    assert btn and not re.search(_BARE_DISABLED, btn.group(0))


def test_app_config_provides_no_http_client():
    cfg = _strip_comments(_APP / "app.config.ts")
    assert "provideHttpClient" not in cfg
    assert "HttpClient" not in cfg


def test_data_and_meta_modules_declare_actions_not_admitted():
    data_ts = (_APP / "workforce" / "workforce-data.ts").read_text()
    meta_ts = (_APP / "workforce" / "workforce-meta.ts").read_text()
    assert '"actionsAdmitted": false' in data_ts
    assert '"actionsAdmitted": false' in meta_ts
    assert LABEL in data_ts and LABEL in meta_ts
    assert "export const WORKFORCE_DATA: WorkforceData =" in data_ts
    assert "export const WORKFORCE_META: WorkforceMeta =" in meta_ts


# The console renders backend data; its public surface is tiny and FIXED. Enforce a
# COMPLETE per-file member allowlist over every workforce class — the robust, name-
# independent guard against a client-side "second brain" (team planner/selector).
_WF_MEMBERS = {
    "workforce.service.ts": {"actionsAdmitted", "characterById", "characters", "data",
                             "divisions", "filterRoster", "frameworks", "notAvailableLabel", "proposals"},
    "roster.component.ts": {"apply", "constructor", "division", "flaggedOnly", "framework",
                            "riskClass", "riskTier", "rows", "search", "selectedId", "shortHash",
                            "sourceKind", "toggle", "total"},
    "team-sim.component.ts": {"constructor", "current", "idx", "proposals", "roleLabel"},
    "matrices.component.ts": {"constructor", "count", "flaggedCount", "frameworkCount"},
    "org-chart.component.ts": {"constructor", "name"},
    "governed-action.component.ts": {"label", "verb"},
}
# Capture a class member after any leading decorators + access/modifier keywords, so a
# planner cannot hide behind `public`/`private`/`static`/`@Input()`/arrow-property syntax.
_MEMBER_RE = re.compile(
    r"^\s{2}(?:@\w+\([^)]*\)\s*)*"
    r"(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|async\s+|get\s+|set\s+)*"
    r"([A-Za-z_]\w*)\s*[(=:]", re.M)


def _class_members(src: str):
    i = src.find("export class ")
    if i < 0:
        return None  # no class (generated data / meta / types)
    return {m for m in _MEMBER_RE.findall(src[i:]) if not m.startswith("_")}


def test_console_carries_no_team_planning_logic():
    # Contract: "the console carries no planning logic and re-computes nothing" — team
    # proposals come from the backend catalog (static exampleProposals). Structural,
    # name-independent guard:
    #  (1) COMPLETE per-file member allowlist over EVERY workforce class — any new
    #      member (any name/modifier/decorator/arrow-property) in any file fails;
    #  (2) the set of workforce CLASS files is itself fixed (a new class file must be
    #      added to the allowlist deliberately);
    #  (3) `.sort(`/`.slice(` forbidden (client-side ranking / top-N selection) and a
    #      team-construction identifier scan — defense-in-depth.
    wf = _APP / "workforce"
    for name, allowed in _WF_MEMBERS.items():
        members = _class_members((wf / name).read_text())
        assert members is not None, f"{name}: expected a class"
        extra = members - allowed
        assert not extra, f"{name}: unexpected public member(s) (possible client-side logic): {extra}"
    class_files = {p.name for p in wf.glob("*.ts")
                   if not p.name.endswith(".spec.ts") and _class_members(p.read_text()) is not None}
    assert class_files == set(_WF_MEMBERS), \
        f"workforce class file set changed (new/removed class must update the allowlist): {class_files ^ set(_WF_MEMBERS)}"

    planning = re.compile(
        r"(?:plan|assemble|recruit|staff|compose|rank|score|pick|select|form|draft|propose|build|make|choose)\w*[Tt]eam",
        re.I)
    for path in wf.glob("*.ts"):
        if path.name.endswith(".spec.ts"):
            continue
        code = _strip_comments(path)
        assert ".sort(" not in code, f"{path.name}: client-side .sort( (ranking) — the UI must render backend-ordered data, not rank"
        assert ".slice(" not in code, f"{path.name}: client-side .slice( (top-N selection) — the UI must not select a subset/team"
        # A read-only render console accumulates no state — it maps/filters/renders.
        # Banning the accumulation/mutation primitives closes planner logic hidden INSIDE
        # an allowlisted method body (or a free function) that builds a selection without
        # sort/slice or a "*Team" name. Clean source uses none (reads are .filter/.find/
        # .includes/.join). NOTE: this is a regression net, not a proof — the DEFINITIVE
        # inertness evidence is the runtime ng-test specs + the compiled-bundle inspection
        # (proposals() returns static backend data; no planning algorithm is compiled in).
        for tok in (".push(", ".reduce(", ".splice(", ".concat(", "new Set", "new Map", "new Array"):
            assert tok not in code, f"{path.name}: {tok!r} — a render console accumulates no state (possible client-side planner)"
        m = planning.search(code)
        assert not m, f"{path.name}: team-construction identifier {m.group(0)!r} — the UI must not compute teams"


def test_no_router_guards_or_resolvers_doing_io():
    routes = (_APP / "app.routes.ts").read_text()
    for tok in ("canActivate", "resolve:", "canMatch", "HttpClient", "fetch("):
        assert tok not in routes, f"app.routes.ts references {tok!r}"


def test_forbidden_scan_has_teeth(tmp_path):
    # The scan must catch a forbidden token planted inside a component inline
    # template (backtick) EVEN WHEN it sits after a `//` inside that template —
    # the backtick-aware strip must preserve template content so the token is still
    # scanned. The token therefore sits after a `//` INSIDE the backtick: a correct
    # backtick-aware strip leaves it intact (flagged), but the natural neuter (drop
    # the backtick split, strip `//` over the whole string) eats it to end-of-line,
    # so `fetch("a")` then vanishes and THIS assertion fails — locking the
    # preservation logic that the earlier (weaker) sample did not catch. The second
    # token, after a `//` OUTSIDE the template, is the negative control: stripped by
    # both, proving the strip still removes genuine line comments.
    f = tmp_path / "sample.ts"
    f.write_text('const t = `<div> // keep fetch("a")`; // drop fetch("b")\n')
    stripped = _strip_comments(f)
    assert 'fetch("a")' in stripped      # inside template, after // -> MUST survive (flagged)
    assert 'fetch("b")' not in stripped  # outside template -> genuine // comment stripped


def test_committed_sbom_licenses_complete_and_match_lockfile():
    # final-review fix: the committed CycloneDX SBOM must carry a license for EVERY
    # component, and each must match the lockfile — guards the earlier under-reporting
    # (122 blanks; MPL-2.0 shown as 2 vs the true 12).
    import collections
    import json
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / "frontend-pilots" / "kai-angular" / "package-lock.json").read_text())
    sbom = json.loads((root / "docs" / "workforce" / "step2-evidence" / "sbom.cyclonedx.json").read_text())
    lock_lic = {}
    for k, v in lock["packages"].items():
        if not k or not v.get("version"):
            continue
        lic = v.get("license")
        if isinstance(lic, list):
            lic = "/".join(str(x) for x in lic)
        lock_lic[(k.split("node_modules/")[-1], v["version"])] = lic
    comps = sbom["components"]
    assert comps and all(c.get("licenses") for c in comps), "SBOM must carry a license for every component"
    # COMPLETE (not just 'match'): the SBOM must cover the WHOLE lockfile — every
    # lockfile package entry present, with the SAME multiplicity, and no phantom
    # extras. Compared against the RAW lockfile entries (not the collapsed lock_lic
    # dict) so the 30 legitimately-nested duplicate name+version pairs must appear in
    # the SBOM too. Guards the under-reporting failure mode the test is named for: a
    # future regenerated SBOM that drops components fails here.
    lock_raw = collections.Counter(
        (k.split("node_modules/")[-1], v["version"])
        for k, v in lock["packages"].items() if k and v.get("version")
    )
    sbom_keys = collections.Counter((c["name"], c["version"]) for c in comps)
    assert sbom_keys == lock_raw, (
        "SBOM does not bijectively cover the lockfile: "
        f"missing_from_sbom={sorted(set(lock_raw) - set(sbom_keys))[:5]}, "
        f"extra_in_sbom={sorted(set(sbom_keys) - set(lock_raw))[:5]}, "
        f"count sbom={sum(sbom_keys.values())} lock={sum(lock_raw.values())}"
    )
    dist = collections.Counter()
    for c in comps:
        lid = c["licenses"][0]["license"]["id"]
        dist[lid] += 1
        assert lock_lic.get((c["name"], c["version"])) == lid, f"SBOM license for {c['name']} != lockfile"
    assert dist["MPL-2.0"] == 12  # copyleft count reported truthfully, not under-counted
