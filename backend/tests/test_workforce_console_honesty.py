"""Phase 5A — static honesty/security checks on the DARK Angular console SOURCE.

Runnable now (pure Python, no Angular toolchain): scans the committed Angular
source for any network or execution pattern, and asserts the console is inert by
construction — no HttpClient/fetch/WebSocket/etc., no enabled action, the canonical
NOT-AVAILABLE label present, every governed action disabled with no event output.
The governed sandbox's `ng test`/`ng build` is the later, separate gate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "frontend-pilots" / "kai-angular" / "src"
_APP = _SRC / "app"
LABEL = "NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED"

_TS_HTML = sorted([*_APP.rglob("*.ts"), *_APP.rglob("*.html")])


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)          # block comments
    src = re.sub(r"(^|\s)//[^\n]*", " ", src)                  # line comments
    return src


# network / execution primitives that must not appear in console CODE
# (dynamic `import(...)` for lazy route code-splitting is standard Angular and
# local-only, so it is NOT forbidden here.)
_FORBIDDEN_CODE = (
    "@angular/common/http", "HttpClient", "provideHttpClient", "HttpClientModule",
    "fetch(", "XMLHttpRequest", "new WebSocket", "new EventSource", "sendBeacon",
    "axios", "eval(", "Function(", "localStorage", "sessionStorage",
    "window.open", ".postMessage(",
)
# execution verbs that must not be invoked by a (click)/action handler
_ACTION_VERBS = ("execute", "dispatch", "activate", "assign", "run", "deploy", "spawn", "enable")


@pytest.mark.parametrize("path", _TS_HTML, ids=lambda p: p.name)
def test_no_network_or_execution_primitive(path):
    code = _strip_comments(path.read_text())
    for tok in _FORBIDDEN_CODE:
        assert tok not in code, f"{path.name} references {tok!r} (console must be inert/offline)"


def test_no_click_handler_invokes_an_action_verb():
    for path in _TS_HTML:
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
    assert "disabled" in ga                       # the button is disabled
    assert "(click)" not in ga                    # no click handler at all
    assert "@Output" not in ga and "EventEmitter" not in ga  # cannot emit an action


def test_app_config_provides_no_http_client():
    cfg = (_APP / "app.config.ts").read_text()
    assert "provideHttpClient" not in cfg
    assert "HttpClient" not in _strip_comments(cfg)


def test_data_module_declares_actions_not_admitted():
    data_ts = (_APP / "workforce" / "workforce-data.ts").read_text()
    assert '"actionsAdmitted": false' in data_ts
    assert LABEL in data_ts
    # sanity: the generated module is the typed WorkforceData, not executable code
    assert "export const WORKFORCE_DATA: WorkforceData =" in data_ts


def test_no_router_guards_or_resolvers_doing_io():
    routes = (_APP / "app.routes.ts").read_text()
    for tok in ("canActivate", "resolve:", "canMatch", "HttpClient", "fetch("):
        assert tok not in routes, f"app.routes.ts references {tok!r}"
