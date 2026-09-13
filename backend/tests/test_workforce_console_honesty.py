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


def test_no_click_handler_invokes_an_action_verb():
    for path in _CODE:
        for m in re.finditer(r"\(click\)=\"([^\"]*)\"", path.read_text()):
            body = m.group(1).lower()
            assert not any(v in body for v in _ACTION_VERBS), \
                f"{path.name}: (click) handler {m.group(1)!r} invokes an action verb"


def test_canonical_label_present_in_action_control_and_shell():
    ga = (_APP / "workforce" / "governed-action.component.ts").read_text()
    shell = (_APP / "app.component.html").read_text()
    assert LABEL in ga
    assert LABEL in shell


def test_governed_action_is_always_disabled_with_no_output():
    ga = (_APP / "workforce" / "governed-action.component.ts").read_text()
    # a REAL bare `disabled` attribute (not merely `aria-disabled`, which is advisory)
    assert re.search(r"(?<![-\w])disabled(?![-\w=])", ga), "governed action button must carry a bare disabled attribute"
    assert "(click)" not in ga                    # no click handler at all
    assert "@Output" not in ga and "EventEmitter" not in ga  # cannot emit an action


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


def test_no_router_guards_or_resolvers_doing_io():
    routes = (_APP / "app.routes.ts").read_text()
    for tok in ("canActivate", "resolve:", "canMatch", "HttpClient", "fetch("):
        assert tok not in routes, f"app.routes.ts references {tok!r}"


def test_forbidden_scan_has_teeth():
    # The scan must catch a forbidden token planted inside a component inline
    # template (backtick), not just in plain code — proving the backtick-aware
    # comment strip does not hide template content.
    sample = 'const t = `<button (click)="run()">x</button> fetch("x")`;'
    # emulate the ts branch of _strip_comments on this snippet
    stripped = "`".join(
        (re.sub(r"//[^\n]*", " ", part) if i % 2 == 0 else part)
        for i, part in enumerate(re.sub(r"/\*.*?\*/", " ", sample, flags=re.S).split("`"))
    )
    assert "fetch(" in stripped  # template content survives stripping -> would be flagged
