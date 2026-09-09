"""The owner API key must never leave the server.

INCIDENT, 2026-09-08. `GET /admin/ceo` and `GET /admin/legacy` returned HTTP 200 to ANONYMOUS
callers with the live owner API key substituted into the page:

    core/api.py  _serve_old_dashboard()
        if _API_KEY:
            html = html.replace("const API_KEY = '';", f"const API_KEY = '{_API_KEY}';")

Confirmed serving a populated key on production (32 chars) and staging (64 chars) — two distinct
key families, both therefore compromised. The value was fingerprinted, never captured.

WHY IT IS SEVERE. That key is not merely a read credential:
  * `verify_api_key` accepts it as `X-API-Key` on the whole owner `/api/*` surface, including writes;
  * `core/api.py:146` passes it as the session `owner_key`, so `POST /admin/session/login`
    {"secret": <key>} MINTS AN OWNER SESSION COOKIE;
  * `resolve_secret` maps it to ROLE_OWNER, which holds ALL_SCOPES — read, write, high_impact,
    financial, destructive, kai.chat, kai.ultra — so it also reaches App B through the bridge.

Authentication is NOT a justification for returning it. An owner already authenticated does not need
the server's own credential delivered into browser JavaScript, where it reaches sessionStorage,
localStorage, extensions, screenshots and any XSS. So these tests assert zero credential bytes for
EVERY identity, not just anonymous.

The pages keep working: `operator_session_enabled` is true in production and staging, and
`verify_api_key` already accepts a valid owner session cookie (`_session_owner_ok`), so same-origin
fetches authenticate without a browser-held key.
"""
import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")
os.environ.setdefault("RELEASE_VERIFIER_SIGNING_SECRET", "verifier-signing-secret")

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

OWNER_KEY = os.environ["API_KEY"]                          # conftest: "ownerkey"
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]
VERIFIER_SECRET = os.environ["RELEASE_VERIFIER_SIGNING_SECRET"]

# The routes that served the key, plus every other page that could pick up the same substitution.
LEAK_ROUTES = ["/admin/ceo", "/admin/legacy", "/admin", "/admin/hub", "/admin/command",
               "/admin/portfolio", "/admin/scoreboard", "/admin/siteboost", "/admin/shopify"]


@pytest.fixture
def client():
    return TestClient(core_api.app)


def _identities():
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    return {
        "anonymous": ({}, {}),
        "owner-key": ({"X-API-Key": OWNER_KEY}, {}),
        "owner-session": ({}, {COOKIE_NAME: osess.mint_session(
            "owner", secret=SESSION_SECRET, ttl_seconds=3600)}),
        "verifier": ({VERIFIER_HEADER: mint_verifier_token(
            subject="incident-suite", secret=VERIFIER_SECRET)}, {}),
        "operator-session": ({}, {COOKIE_NAME: osess.mint_session(
            "operator", secret=SESSION_SECRET, ttl_seconds=3600)}),
        "signed-out": ({}, {COOKIE_NAME: ""}),
        "bad-key": ({"X-API-Key": "not-the-owner-key"}, {}),
    }


def _assert_no_key(body: str, where: str):
    """Zero credential bytes — the value, and anything it could be reconstructed from."""
    assert OWNER_KEY not in body, f"{where} contains the owner key verbatim"
    # A populated assignment is the leak shape, whatever the value happens to be.
    m = re.search(r"const API_KEY\s*=\s*'([^']*)'", body)
    if m:
        assert m.group(1) == "", (
            f"{where} ships a POPULATED const API_KEY (len={len(m.group(1))}) — the injection is back")
    for enc in (OWNER_KEY.encode().hex(), OWNER_KEY[::-1]):
        assert enc not in body, f"{where} contains a reversible encoding of the owner key"


# ── 1. no identity may receive the credential ─────────────────────────────────────────────────────
@pytest.mark.parametrize("path", LEAK_ROUTES)
@pytest.mark.parametrize("label", sorted(_identities()))
def test_no_identity_receives_the_owner_key(client, path, label):
    headers, cookies = _identities()[label]
    r = client.get(path, headers=headers, cookies=cookies)
    _assert_no_key(r.text, f"{path} [{label}] ({r.status_code})")


@pytest.mark.parametrize("path", ["/admin/ceo", "/admin/legacy"])
def test_the_incident_routes_still_serve_their_page(client, path):
    """Containment must not be achieved by breaking the page."""
    r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert len(r.content) > 5_000, "the dashboard shell did not render"


# ── 2. no request shape recovers it ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/admin/ceo", "/admin/legacy"])
@pytest.mark.parametrize("shape,label", [
    (lambda p: (p + "?key=x", {}), "query-key"),
    (lambda p: (p + f"?api_key={OWNER_KEY}", {}), "query-api-key"),
    (lambda p: (p + "?debug=1", {}), "query-debug"),
    (lambda p: (p + "/", {}), "trailing-slash"),
    (lambda p: (p, {"Accept": "application/json"}), "accept-json"),
    (lambda p: (p, {"Accept": "*/*"}), "accept-any"),
    (lambda p: (p, {"X-Requested-With": "XMLHttpRequest"}), "xhr"),
    (lambda p: (p.replace("/admin/", "/./admin/", 1), {}), "dot-segment"),
    (lambda p: (p.replace("/admin/", "//admin/", 1), {}), "double-slash"),
    (lambda p: (p.upper(), {}), "uppercase"),
])
def test_no_request_shape_recovers_the_owner_key(client, path, shape, label):
    url, headers = shape(path)
    r = client.get(url, headers=headers, follow_redirects=True)
    _assert_no_key(r.text, f"{url} [{label}] ({r.status_code})")


@pytest.mark.parametrize("path", ["/admin/ceo", "/admin/legacy"])
def test_head_and_error_bodies_carry_no_key(client, path):
    _assert_no_key(client.head(path).text, f"HEAD {path}")
    _assert_no_key(client.get(path + "/nonexistent-subpath").text, f"404 under {path}")


# ── 3. THE SWEEP: nothing the app serves may contain it ───────────────────────────────────────────
def test_no_served_route_anywhere_contains_the_owner_key(client):
    """The incident was found on two routes. This asserts the property across every GET route the
    app exposes, so a third one cannot appear quietly — including the /admin JS and CSS assets,
    which are served to anonymous callers."""
    offenders = []
    for route in core_api.app.routes:
        path = getattr(route, "path", "") or ""
        methods = getattr(route, "methods", set()) or set()
        if not path or "{" in path or "GET" not in methods:
            continue
        try:
            r = client.get(path, follow_redirects=False)
        except Exception:                                  # noqa: BLE001 — a route that raises leaks nothing
            continue
        body = r.text
        if OWNER_KEY in body:
            offenders.append(f"{path} -> {r.status_code} ({len(r.content)} B)")
        m = re.search(r"const API_KEY\s*=\s*'([^']+)'", body)
        if m:
            offenders.append(f"{path} -> populated const API_KEY (len={len(m.group(1))})")
    assert not offenders, "owner key served by: " + "; ".join(offenders)


# ── 4. the source may not reintroduce it ──────────────────────────────────────────────────────────
def _py_code_only(src: str) -> str:
    """Executable Python, comments stripped.

    The removed code is quoted verbatim in a comment above the deletion, deliberately — this project
    supersedes wrong code visibly rather than erasing it. A guard that greps raw source would force
    that record to be deleted to stay green, so it must read the CODE.
    """
    out = []
    for line in src.splitlines():
        q = None
        for i, ch in enumerate(line):
            if q:
                if ch == q and line[i - 1:i] != "\\":
                    q = None
            elif ch in "'\"":
                q = ch
            elif ch == "#":
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def _js_code_only(src: str) -> str:
    """Executable JS, // and /* */ comments stripped."""
    src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in src.splitlines())


def test_the_substitution_is_gone_from_the_source():
    """MUTATION GUARD. The leak was one f-string. Reintroducing it fails here by name rather than
    waiting for a page scan to notice."""
    import inspect as _inspect
    code = _py_code_only(_inspect.getsource(core_api._serve_old_dashboard))
    assert "_API_KEY" not in code, "_serve_old_dashboard references the owner key again"
    assert "const API_KEY" not in code, "_serve_old_dashboard is templating the key back in"
    # the historical record must survive, so the next reader knows what was removed and why
    raw = _inspect.getsource(core_api._serve_old_dashboard)
    assert "INCIDENT 2026-09-08" in raw, "the incident record was deleted from the fixed function"


def test_no_dashboard_template_carries_a_populated_key():
    """The served FILES must ship an empty literal, so even a bad server-side change has nothing to
    substitute into."""
    from pathlib import Path
    root = Path(core_api.__file__).resolve().parents[1]
    for name in ("ceo.html", "index.html"):
        p = root / "dashboard" / name
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"const API_KEY\s*=\s*'([^']*)'", txt):
            assert m.group(1) == "", f"dashboard/{name} ships a populated API_KEY literal"


# ── 5. the pages must not put a credential in a URL or demand one ─────────────────────────────────
def _ceo_code() -> str:
    from pathlib import Path
    root = Path(core_api.__file__).resolve().parents[1]
    return _js_code_only(
        (root / "dashboard" / "ceo.html").read_text(encoding="utf-8", errors="replace"))


def test_ceo_page_does_not_accept_a_credential_from_the_url():
    """`?key=` put an owner credential in a URL — edge logs, Referer headers, browser history. The
    page authenticates by session cookie now, so it must not read one from the query string."""
    code = _ceo_code()
    assert "searchParams.get('key')" not in code, "ceo.html still reads a credential from the URL"
    assert 'searchParams.get("key")' not in code


def test_ceo_page_does_not_prompt_the_operator_for_the_owner_key():
    """A prompt() for the owner key is how the credential gets back into browser storage. With
    session auth live, the page should never ask."""
    code = _ceo_code()
    assert "prompt(" not in code, "ceo.html still prompts for an owner key"
    assert "ceo_key" not in code, "ceo.html still reads or writes the key in browser storage"


def test_ceo_page_sends_no_api_key_header():
    """The page must not hold a credential to send. Its api() helper builds headers from opts only."""
    code = _ceo_code()
    assert "X-API-Key" not in code, "ceo.html still sends an owner key header"


def test_session_cookie_authenticates_the_api_the_pages_call(client):
    """The containment rests on this: the pages work without a browser-held key because a valid
    owner session already authenticates /api/*. If this ever stops being true, removing the
    injection would break the dashboard and someone would be tempted to put it back."""
    anon = client.get("/api/bots")
    assert anon.status_code == 401, "the /api surface is not gated at all"

    owner = client.get("/api/bots", cookies={COOKIE_NAME: osess.mint_session(
        "owner", secret=SESSION_SECRET, ttl_seconds=3600)})
    assert owner.status_code == 200, (
        "an owner SESSION cannot read /api — the pages would need a browser-held key, which is "
        "exactly what this incident is about")
