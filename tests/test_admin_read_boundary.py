"""App A administrative-read-boundary contract (hotfix: anonymous /admin JSON).

WHY THIS EXISTS. `verify_api_key` returns early for any path that does not start with `/api/`
(core/api.py), so the whole `/admin/*` JSON surface is exempt from the global guard BY CONSTRUCTION.
PR #70 closed that on three routes by adding `Depends(require_admin_json)` to `/admin/registry.json`,
`/admin/capabilities.json` and `/admin/command/metrics.json` — but it added no route-contract test,
and four sibling surfaces carrying the same data classes were left anonymous. All four were confirmed
returning HTTP 200 with no credential against production on 2026-09-08:

    /admin/capabilities                 (Accept: application/json)  126-capability catalogue
    /admin/capabilities/{cap_id}                                    per-capability detail
    /admin/kai-capability-catalog.json  (static asset)              114,215 B — the SAME catalogue
    /admin/automations.json                                         8,465 B — scheduler inventory
                                                                    (137 jobs, cadence, next_run),
                                                                    autopilot posture, integration
                                                                    configuration flags

This module is the missing route contract. It is written so that REMOVING any single guard makes a
specific check fail with the anonymous exposure it permits, rather than failing generically — that is
what makes it a mutation test and not a smoke test.

The gate is `require_admin_json`, unchanged: owner API key, OR owner-role session, OR a signed
server-minted release-verifier token (read-only). This module must never relax it.
"""
import base64
import json
import os

import pytest
from fastapi.testclient import TestClient

# Must precede the core.api import: the fabric flag is read at module scope. The handler re-reads the
# module attribute at call time, so the fixture below also patches it — belt and braces, because a
# 404 from a disabled fabric would mask a missing auth guard and make this suite pass vacuously.
os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")
os.environ.setdefault("RELEASE_VERIFIER_SIGNING_SECRET", "verifier-signing-secret")

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

OWNER_KEY = os.environ["API_KEY"]                          # conftest: "ownerkey"
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]      # conftest: shared surrogate
VERIFIER_SECRET = os.environ["RELEASE_VERIFIER_SIGNING_SECRET"]

# The four surfaces this hotfix protects. `catalog_marker` is a string that appears ONLY in the
# protected payload, so a check can assert the body did not leak without pinning the whole document.
PROTECTED = [
    pytest.param("/admin/capabilities", {"Accept": "application/json"}, "capabilities",
                 id="capabilities-json"),
    pytest.param("/admin/capabilities/kai-memory", {"Accept": "application/json"}, "id",
                 id="capability-detail"),
    pytest.param("/admin/kai-capability-catalog.json", {}, "capabilities",
                 id="static-catalog-asset"),
    pytest.param("/admin/automations.json", {}, "scheduler",
                 id="automations-inventory"),
]
PROTECTED_PATHS = [p.values[0] for p in PROTECTED]


@pytest.fixture(autouse=True)
def _fabric_on(monkeypatch):
    """Force the capability fabric ON for every check.

    Without this a disabled fabric answers 404, an anonymous caller sees no data, and every
    "anonymous is refused" assertion would pass while the guard was absent. A vacuous pass on a
    security control is worse than no test.
    """
    monkeypatch.setattr(core_api, "_CAPABILITY_FABRIC_ENABLED", True, raising=False)


@pytest.fixture
def client():
    return TestClient(core_api.app)


# ── identities ────────────────────────────────────────────────────────────────────────────────────
def _owner_key_headers():
    return {"X-API-Key": OWNER_KEY}


def _owner_session_cookies():
    return {COOKIE_NAME: osess.mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)}


def _verifier_headers(ttl=3600, now=None):
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    return {VERIFIER_HEADER: mint_verifier_token(
        subject="hotfix-suite", secret=VERIFIER_SECRET, ttl_seconds=ttl, now=now)}


def _tampered_verifier_headers():
    """A structurally valid token whose PAYLOAD was edited after signing."""
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    tok = mint_verifier_token(subject="hotfix-suite", secret=VERIFIER_SECRET)
    body, sig = tok.split(".")
    raw = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    raw["role"] = "owner"                                   # privilege escalation attempt
    new = base64.urlsafe_b64encode(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    return {VERIFIER_HEADER: f"{new}.{sig}"}


def _unsigned_verifier_headers():
    """The payload alone, with no signature segment at all."""
    from app.services.holding.verifier_role import VERIFIER_HEADER
    raw = json.dumps({"v": 1, "role": "release_verifier", "sub": "x", "iat": 0, "exp": 9_999_999_999},
                     sort_keys=True, separators=(",", ":")).encode()
    return {VERIFIER_HEADER: base64.urlsafe_b64encode(raw).decode().rstrip("=")}


def _forged_verifier_headers():
    """Correctly shaped and correctly signed — with the WRONG secret."""
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    return {VERIFIER_HEADER: mint_verifier_token(
        subject="attacker", secret="not-the-server-signing-secret")}


# ── 1. anonymous is refused, on every surface ─────────────────────────────────────────────────────
@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_anonymous_get_is_401(client, path, headers, marker):
    r = client.get(path, headers=headers)
    assert r.status_code == 401, f"{path} answered {r.status_code} anonymously"


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_anonymous_error_body_carries_no_protected_content(client, path, headers, marker):
    """A 401 must not smuggle the payload out in its error body."""
    r = client.get(path, headers=headers)
    body = r.text
    assert marker not in body, f"{path} leaked '{marker}' inside its 401 body"
    assert len(body) < 512, f"{path} 401 body is {len(body)} B — too large to be a bare error"


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_anonymous_head_returns_no_protected_content(client, path, headers, marker):
    """HEAD must not be a side door. Either it is refused, or it carries no body."""
    r = client.head(path, headers=headers)
    assert r.status_code in (401, 405), f"{path} HEAD answered {r.status_code} anonymously"
    assert marker not in r.text


# ── 2. authorized identities still read, and read the SAME thing ──────────────────────────────────
@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_owner_api_key_reads(client, path, headers, marker):
    r = client.get(path, headers={**headers, **_owner_key_headers()})
    assert r.status_code == 200, f"owner API key refused on {path}: {r.status_code}"
    assert marker in r.text


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_owner_session_reads(client, path, headers, marker):
    r = client.get(path, headers=headers, cookies=_owner_session_cookies())
    assert r.status_code == 200, f"owner session refused on {path}: {r.status_code}"
    assert marker in r.text


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_release_verifier_reads(client, path, headers, marker):
    """The verifier role exists precisely so automated verification can READ without acting."""
    r = client.get(path, headers={**headers, **_verifier_headers()})
    assert r.status_code == 200, f"release verifier refused on {path}: {r.status_code}"
    assert marker in r.text


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_payload_is_semantically_identical_across_authorized_identities(client, path, headers, marker):
    """Authentication must not change WHAT an authorized reader gets. If these ever diverge, the fix
    has started shaping the payload to satisfy a test — which the hotfix scope forbids."""
    a = client.get(path, headers={**headers, **_owner_key_headers()})
    b = client.get(path, headers=headers, cookies=_owner_session_cookies())
    c = client.get(path, headers={**headers, **_verifier_headers()})
    assert a.status_code == b.status_code == c.status_code == 200
    try:                                    # automations.json carries a generated_at timestamp
        ja, jb, jc = a.json(), b.json(), c.json()
        for j in (ja, jb, jc):
            j.pop("generated_at", None)
        assert ja == jb == jc, f"{path} differs between authorized identities"
    except ValueError:
        assert a.content == b.content == c.content


# ── 3. every invalid identity is refused ──────────────────────────────────────────────────────────
def _bad_identities():
    return {
        "forged-verifier": ({**_forged_verifier_headers()}, {}),
        "unsigned-verifier": ({**_unsigned_verifier_headers()}, {}),
        "tampered-verifier": ({**_tampered_verifier_headers()}, {}),
        "expired-verifier": ({**_verifier_headers(ttl=1, now=1)}, {}),
        "empty-verifier": ({"x-kai-verifier-token": ""}, {}),
        "wrong-api-key": ({"X-API-Key": "not-the-owner-key"}, {}),
        "non-owner-session": ({}, {COOKIE_NAME: osess.mint_session(
            "operator", secret=SESSION_SECRET, ttl_seconds=3600)}),
        "viewer-session": ({}, {COOKIE_NAME: osess.mint_session(
            "viewer", secret=SESSION_SECRET, ttl_seconds=3600)}),
        "signed-out": ({}, {COOKIE_NAME: ""}),
        "garbage-cookie": ({}, {COOKIE_NAME: "not.a.session"}),
        "expired-session": ({}, {COOKIE_NAME: osess.mint_session(
            "owner", secret=SESSION_SECRET, ttl_seconds=1)}),
        "foreign-secret-session": ({}, {COOKIE_NAME: osess.mint_session(
            "owner", secret="a-different-signing-secret", ttl_seconds=3600)}),
    }


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
@pytest.mark.parametrize("label", sorted(_bad_identities()))
def test_invalid_identities_are_refused(client, path, headers, marker, label):
    extra_headers, cookies = _bad_identities()[label]
    if label == "expired-session":
        import time as _t
        _t.sleep(1.1)
    r = client.get(path, headers={**headers, **extra_headers}, cookies=cookies)
    assert r.status_code == 401, f"{label} was accepted on {path} ({r.status_code})"
    assert marker not in r.text


# ── 4. no bypass through path or negotiation tricks ───────────────────────────────────────────────
@pytest.mark.parametrize("path,headers,marker", PROTECTED)
@pytest.mark.parametrize("mutate,label", [
    (lambda p: p + "/", "trailing-slash"),
    (lambda p: p + "?api_key=ownerkey", "credential-in-query-string"),
    (lambda p: p + "?x=1", "query-string"),
    (lambda p: p.replace("/admin/", "/admin%2F", 1), "encoded-separator"),
    (lambda p: p.replace("/admin/", "/./admin/", 1), "dot-segment"),
    (lambda p: p.replace("/admin/", "//admin/", 1), "double-slash"),
])
def test_no_anonymous_bypass_via_path_shape(client, path, headers, marker, mutate, label):
    """A rewritten path must never reach the payload anonymously. 401/404/307/308 are all acceptable;
    a 200 carrying the marker is not.

    `credential-in-query-string` is deliberately included: the hotfix must not introduce a
    URL-borne credential path, so supplying one must NOT authenticate.
    """
    r = client.get(mutate(path), headers=headers, follow_redirects=False)
    assert not (r.status_code == 200 and marker in r.text), \
        f"{label} reached {path} anonymously ({r.status_code})"


@pytest.mark.parametrize("accept", [
    "application/json", "*/*", "text/html,application/json;q=0.9",
    "application/json;q=1.0,text/html;q=0.1", "", "application/*",
])
def test_capabilities_content_negotiation_never_leaks_json_anonymously(client, accept):
    """`/admin/capabilities` picks HTML or JSON from Accept. No negotiation may yield the catalogue
    to an anonymous caller — that content-negotiated JSON path is the original exposure."""
    r = client.get("/admin/capabilities", headers={"Accept": accept} if accept else {})
    assert r.status_code == 401, f"Accept={accept!r} answered {r.status_code} anonymously"
    assert "capabilities" not in r.text


@pytest.mark.parametrize("identity", ["owner-key", "owner-session", "verifier"])
@pytest.mark.parametrize("accept,expect_json", [
    ("application/json", True),
    ("text/html", False),
    ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", False),   # a real browser
    ("text/html,application/json", False),                                        # both -> page wins
])
def test_authorized_accept_negotiation_is_unchanged(client, identity, accept, expect_json):
    """The gate must not change WHICH representation an authorized caller gets.

    Adding authentication to a content-negotiating route is exactly how a page silently becomes a
    JSON blob and navigation breaks. This pins both branches for all three authorized identities.
    """
    kw = {"headers": {"Accept": accept}}
    if identity == "owner-key":
        kw["headers"].update(_owner_key_headers())
    elif identity == "owner-session":
        kw["cookies"] = _owner_session_cookies()
    else:
        kw["headers"].update(_verifier_headers())

    r = client.get("/admin/capabilities", **kw)
    assert r.status_code == 200
    ctype = r.headers.get("content-type", "")
    if expect_json:
        assert "application/json" in ctype, f"{identity}/{accept} lost the JSON branch"
        assert r.json()["count"] == len(r.json()["capabilities"])
    else:
        assert "text/html" in ctype, f"{identity}/{accept} was served JSON instead of the page"
        assert "<html" in r.text.lower(), "the capabilities page shell did not render"


def test_static_catalog_alias_is_not_an_alternate_anonymous_route(client):
    """The static asset is the SAME data as /admin/capabilities. Gating one and not the other leaves
    the exposure open, which is exactly what the enumeration found."""
    for p in ("/admin/kai-capability-catalog.json", "/admin/capabilities"):
        r = client.get(p, headers={"Accept": "application/json"})
        assert r.status_code == 401, f"{p} is an anonymous alias for the catalogue"


# ── 5. caching must not preserve an anonymous copy ────────────────────────────────────────────────
@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_protected_responses_are_no_store(client, path, headers, marker):
    """`no-store` is what stops an intermediary or a browser retaining the protected body — and what
    stops a signed-out refresh replaying it out of cache."""
    r = client.get(path, headers={**headers, **_owner_key_headers()})
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "").lower(), \
        f"{path} authorized response is missing Cache-Control: no-store"


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_authenticated_read_does_not_warm_an_anonymous_copy(client, path, headers, marker):
    """Read as owner, then anonymously. The second must still be refused."""
    ok = client.get(path, headers={**headers, **_owner_key_headers()})
    assert ok.status_code == 200
    anon = client.get(path, headers=headers)
    assert anon.status_code == 401, f"{path} served a cached anonymous copy after an authorized read"
    assert marker not in anon.text


# ── 6. no credential reflection ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_no_credential_reflection(client, path, headers, marker):
    """Neither the payload nor the error may echo any credential material back."""
    secrets = (OWNER_KEY, SESSION_SECRET, VERIFIER_SECRET)
    responses = [
        client.get(path, headers={**headers, **_owner_key_headers()}),
        client.get(path, headers=headers, cookies=_owner_session_cookies()),
        client.get(path, headers={**headers, **_verifier_headers()}),
        client.get(path, headers=headers),
        client.get(path, headers={**headers, "X-API-Key": "not-the-owner-key"}),
    ]
    for r in responses:
        blob = r.text + json.dumps(dict(r.headers))
        for s in secrets:
            assert s not in blob, f"{path} reflected a credential ({r.status_code})"


# ── 7. capability detail still behaves ────────────────────────────────────────────────────────────
def test_capability_detail_rejects_unknown_id_for_authorized_reader(client):
    r = client.get("/admin/capabilities/no-such-capability-xyz",
                   headers={"Accept": "application/json", **_owner_key_headers()})
    assert r.status_code == 404


@pytest.mark.parametrize("bad", ["../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "", " ", "%00"])
def test_capability_detail_rejects_malformed_ids(client, bad):
    r = client.get(f"/admin/capabilities/{bad}",
                   headers={"Accept": "application/json", **_owner_key_headers()},
                   follow_redirects=False)
    assert r.status_code != 200 or "passwd" not in r.text


# ── 8. pre-authentication assets must NOT be gated ────────────────────────────────────────────────
# The static-catalog guard must be surgical. Gating the whole asset router would break every admin
# page, the presence layer and the login surface — a self-inflicted outage dressed as a security fix.
PUBLIC_ASSETS = [
    "/admin/kai-presence.js", "/admin/kai-presence.css", "/admin/kai-nexus.js",
    "/admin/kai-nexus.css", "/admin/kai-speech-input.js", "/admin/kai-tts-provider.js",
    "/admin/kai-gesture.js", "/admin/kai-nexus-capabilities.js",
]


@pytest.mark.parametrize("path", PUBLIC_ASSETS)
def test_pre_auth_assets_remain_public(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} must stay public — gating it breaks the admin UI"


def test_ui_config_remains_public(client):
    """Reviewed and deliberately out of scope: authentication itself depends on it, and its contract
    is boolean-only."""
    r = client.get("/admin/ui-config")
    assert r.status_code == 200
    assert set(r.json()) == {"operator_session_enabled", "kai_bridge_enabled",
                             "kai_command_bar_governed"}
    assert all(isinstance(v, bool) for v in r.json().values())


def test_bridge_health_remains_public_and_leaks_no_upstream(client):
    """Recorded low-severity public diagnostic residual. Unchanged by this hotfix, but pinned so it
    cannot silently start disclosing the upstream URL."""
    r = client.get("/admin/kai-bridge/health")
    assert r.status_code == 200
    body = r.text
    assert os.getenv("KAI_UPSTREAM_URL", "http://kai-upstream.local") not in body
    assert r.json().get("upstream_configured") in (True, False)


def test_whoami_is_public_and_anonymous_discloses_nothing(client):
    """Reviewed public endpoint: authentication itself depends on it. Pinned because it is the one
    reviewed exception that COULD leak — it returns a role and scopes. Anonymously it must disclose
    neither, and with a session it must describe only that caller."""
    anon = client.get("/admin/session/whoami")
    assert anon.status_code == 200
    assert anon.json() == {"authenticated": False, "role": "anonymous", "scopes": []}

    owner = client.get("/admin/session/whoami", cookies=_owner_session_cookies())
    assert owner.json()["authenticated"] is True and owner.json()["role"] == "owner"
    # It describes the caller, never the system: no catalogue, no schedule, no inventory.
    assert set(owner.json()) <= {"authenticated", "role", "scopes", "source"}


# ── 9. route contract — the guard cannot be removed silently ──────────────────────────────────────
def _auth_dependency_names(path: str) -> set:
    names = set()
    for route in core_api.app.routes:
        if getattr(route, "path", None) != path:
            continue
        stack = list(getattr(getattr(route, "dependant", None), "dependencies", []) or [])
        while stack:
            sub = stack.pop()
            call = getattr(sub, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            stack.extend(getattr(sub, "dependencies", []) or [])
    return names


@pytest.mark.parametrize("path", ["/admin/capabilities", "/admin/capabilities/{cap_id}",
                                  "/admin/kai-capability-catalog.json",
                                  "/admin/automations.json"])
def test_route_declares_the_auth_dependency(path):
    """MUTATION GUARD. Deleting `Depends(require_admin_json)` from any of these fails here by name,
    so the regression is reported as 'the guard is gone' rather than as a confusing 200."""
    assert "require_admin_json" in _auth_dependency_names(path), \
        f"{path} lost its require_admin_json dependency"


def test_static_catalog_is_guarded_before_its_bytes_are_read():
    """The static asset is guarded inside the route factory, not by a dependency, so the contract is
    asserted differently: the protected name must be in the guarded set, and the guard must run
    BEFORE the file is opened."""
    assert "kai-capability-catalog.json" in core_api._PROTECTED_NEXUS_ASSETS
    assert not (set(core_api._PROTECTED_NEXUS_ASSETS) - set(core_api._NEXUS_APP_MIME)), \
        "a protected asset name that is not served at all is a typo, not a guard"
    # Every OTHER asset must stay public — this is the blast-radius pin.
    assert len(core_api._PROTECTED_NEXUS_ASSETS) == 1


def test_no_other_admin_json_route_is_anonymous(client):
    """Standing enumeration guard. A NEW unauthenticated /admin/* JSON route fails here rather than
    waiting to be found in production.

    Three reviewed exceptions, each anonymous BY REQUIREMENT and each pinned by its own check above:
      /admin/ui-config          three non-secret booleans; the login surface reads it pre-auth
      /admin/kai-bridge/health  bridge diagnostics; never carries the upstream URL or a secret
      /admin/session/whoami     "am I logged in?"; anonymously it answers
                                {"authenticated": false, "role": "anonymous", "scopes": []} and
                                reflects only the CALLER'S OWN identity when they present a session
    """
    reviewed_public = {"/admin/ui-config", "/admin/kai-bridge/health", "/admin/session/whoami"}
    offenders = []
    for route in core_api.app.routes:
        path = getattr(route, "path", "") or ""
        if not path.startswith("/admin") or path in reviewed_public:
            continue
        if "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        if _auth_dependency_names(path):
            continue
        r = client.get(path, headers={"Accept": "application/json"}, follow_redirects=False)
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and "application/json" in ctype:
            offenders.append(f"{path} -> 200 {ctype} ({len(r.content)} B)")
    assert not offenders, "anonymous /admin JSON: " + "; ".join(offenders)
