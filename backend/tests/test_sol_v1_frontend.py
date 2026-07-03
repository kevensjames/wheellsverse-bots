"""Stage 6 tests — the Sol v1 mobile-first member app (static SPA).

Covers: the three static files exist and are wired; app.js parses (node --check)
and its pure helpers pass their JS unit tests (node app.test.js); every fetch the
SPA makes resolves to a REAL registered backend route (endpoint-contract); and
the non-custodial disclosure + secure-by-construction properties hold.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "sol_v1_app"
APP_JS = APP_DIR / "app.js"
INDEX = APP_DIR / "index.html"
STYLES = APP_DIR / "styles.css"
NODE = shutil.which("node")


# ── files exist + are wired ──────────────────────────────────────────────────

def test_static_files_exist():
    assert INDEX.is_file() and APP_JS.is_file() and STYLES.is_file()
    assert (APP_DIR / "terms.html").is_file()  # Stage 7 legal document
    html = INDEX.read_text()
    assert 'src="app.js"' in html and 'href="styles.css"' in html
    assert 'name="viewport"' in html  # mobile-first


def test_app_mounted_in_main():
    main = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    assert '"/sol-app"' in main and "sol_v1_app" in main


# ── no XSS surface: user data never flows through innerHTML ───────────────────

def test_no_innerhtml_sink():
    js = APP_JS.read_text()
    assert ".innerHTML" not in js, "app.js must not use innerHTML (XSS surface)"


def test_non_custodial_disclosure_present():
    js = APP_JS.read_text().lower()
    assert "never" in js and ("hold" in js or "custod" in js)
    assert "pay each other" in js  # the core non-custodial framing


# ── node: syntax + pure-helper unit tests ────────────────────────────────────

@pytest.mark.skipif(not NODE, reason="node not available")
def test_appjs_parses():
    r = subprocess.run([NODE, "--check", str(APP_JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not NODE, reason="node not available")
def test_pure_helpers_js_unit_tests():
    r = subprocess.run([NODE, "--test", "app.test.js"], capture_output=True, text=True, cwd=str(APP_DIR))
    assert r.returncode == 0, (r.stdout + "\n" + r.stderr)


# ── endpoint contract: every fetch resolves to a real route ──────────────────

def _shape(path: str) -> tuple[str, ...]:
    """Normalize a URL path to segments with params collapsed to '{}'."""
    segs = []
    for s in path.strip("/").split("/"):
        segs.append("{}" if (s.startswith("{") or s == "{}" or s == "") else s)
    return tuple(segs)


def _seg_match(front: tuple[str, ...], route: tuple[str, ...]) -> bool:
    if len(front) != len(route):
        return False
    return all(a == b or a == "{}" or b == "{}" for a, b in zip(front, route))


def _candidate_shapes(expr: str) -> list[tuple[str, ...]]:
    """Path shapes a single api() path-expression could resolve to.

    - concatenation ("/a/" + id + "/b") → one shape with vars collapsed to {}
    - ternary / single literal → each "/..."-literal is its own full-path shape
    - bare variable (no literal) → [] (can't verify statically)
    """
    expr = expr.strip()
    if "+" in expr:
        parts = [p.strip() for p in expr.split("+")]
        out = "".join(p[1:-1] if (len(p) >= 2 and p[0] == '"' and p[-1] == '"') else "{}" for p in parts)
        return [_shape(out)]
    return [_shape(lit) for lit in re.findall(r'"(/[^"]*)"', expr)]


def _api_calls(js: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).strip())
            for m in re.finditer(r'api\(\s*"(\w+)"\s*,\s*([^,)]+)', js)]


def test_every_frontend_fetch_hits_a_real_route():
    from app.main import app

    route_shapes: set[tuple[str, tuple[str, ...]]] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods:
            continue
        shp = _shape(path)
        for meth in methods:
            route_shapes.add((meth.upper(), shp))

    calls = _api_calls(APP_JS.read_text())
    assert calls, "expected to extract api() calls from app.js"

    unmatched = []
    for method, expr in calls:
        shapes = _candidate_shapes(expr)
        if not shapes:
            continue  # dynamic bare-variable path — can't statically verify
        for fshape in shapes:
            if not any(rm == method and _seg_match(fshape, rshape) for rm, rshape in route_shapes):
                unmatched.append(f"{method} /{'/'.join(fshape)}  (expr: {expr})")

    assert not unmatched, "frontend calls with no matching backend route:\n" + "\n".join(sorted(set(unmatched)))


def test_contract_covers_the_core_endpoints():
    """Guard that the SPA actually wires the key flows (not just that what it
    calls exists) — catches a screen that silently stopped calling an endpoint."""
    js = APP_JS.read_text()
    for needed in [
        '"/auth/login"', '"/auth/me"', '"/sol/v1/groups"', '"/sol/v1/groups/join"',
        '"/sol/v1/reminders"', '"/sol/v1/reputation/me"', '"/sol/v1/payment-profiles"',
        "/mark", "/activate", "/lock",   # literal path suffixes
        '"confirm"', '"dispute"',        # actions built dynamically in paymentAction
        '"/sol/v1/legal/current"', '"/sol/v1/legal/accept"', "#/consent",  # Stage 7 gate
    ]:
        assert needed in js, f"SPA no longer references {needed}"
