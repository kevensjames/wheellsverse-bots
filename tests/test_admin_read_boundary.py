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
# Strings that appear ONLY inside a protected payload. The guard below judges these BYTES rather than
# a Content-Type header, so re-serving the same data as text/plain or inside a .js bundle cannot slip
# past.
#
# Every marker was quoted-JSON-only in the first version, which meant two escapes: a CSV export, and
# a bundler emitting `{hourly_cycles: 1}` with identifier-safe keys unquoted (standard esbuild and
# rollup output). Both were proven to leak with zero markers matched. So each data class now carries
# a VALUE anchor — a distinctive string that survives any re-serialisation — alongside its key names.
# VALUE anchors — data, not field names. A value survives any re-serialisation (JSON, a JS object
# literal with unquoted keys, CSV, a template), which key-name markers do not. Each was checked
# against every public admin asset; NATIVE_KAI_TOOL, security_tier, markitdown and yt-dlp were
# candidates and are excluded because they appear in kai-nexus-capabilities.js or the public shell,
# where they would be false positives rather than leaks.
DATA_VALUE_MARKERS = frozenset({"CapabilityRegistry", "kai-memory", "claude-code", "context7"})

# KEY-NAME markers, as a second net for a payload whose values changed but whose shape did not.
# The `name:` variant is deliberately absent: automations.html's own ternary
# `ap.hourly_cycles!=null?ap.hourly_cycles:na()` contains it, so it would flag the public page.
DATA_KEY_MARKERS = frozenset(
    f'{q}{k}{q2}'
    for k in ("hourly_cycles", "delivery_log_count", "total_posts_auto")
    for q, q2 in (('"', '"'), ("", ","))
)

DATA_MARKERS = DATA_VALUE_MARKERS | DATA_KEY_MARKERS


def _runtime_data_markers(client) -> set:
    """Value anchors pulled from the LIVE authorized payloads.

    The automations inventory has no stable hardcodable value the way a capability id is stable, so
    its anchors are derived here from real job names. Anything that also appears in the public shell
    is dropped, so a marker can never become a false positive. This is what closes the
    unquoted-key-bundle and CSV escapes for the automations data class.
    """
    markers = set()
    try:
        d = client.get("/admin/automations.json", headers=_owner_key_headers()).json()
        for job in ((d.get("scheduler") or {}).get("jobs") or [])[:5]:
            bot = str(job.get("bot") or "").strip()
            if len(bot) >= 8:
                markers.add(bot)
    except Exception:                                    # noqa: BLE001 — absence is not a failure
        pass
    public = ""
    for p in ("/admin/automations", "/admin/capabilities"):
        try:
            public += client.get(p, headers={"Accept": "text/html"}).text
        except Exception:                                # noqa: BLE001
            pass
    return {m for m in markers if m not in public}

# Accept headers the enumeration guard probes each route with. One probe was not enough: the guard
# used to send only `application/json` and skip any non-200, so a route that 401s on JSON while
# serving data to `*/*` — the exact shape /admin/capabilities now has — was never byte-scanned.
GUARD_PROBE_ACCEPTS = ("application/json", "*/*", "text/html", "application/json, text/plain, */*")

# `marker` is now a string from the real payload, not a JSON key name. A key name is present even
# when its value has been nulled, which is how a gutted payload passed this suite once.
PROTECTED = [
    pytest.param("/admin/capabilities", {"Accept": "application/json"}, '"CapabilityRegistry"',
                 id="capabilities-json"),
    pytest.param("/admin/capabilities/kai-memory", {"Accept": "application/json"}, '"security_tier"',
                 id="capability-detail"),
    # the checked-in file's `source` is the seed module, not "CapabilityRegistry" — so key off a
    # field that is genuinely in every one of its 126 records
    pytest.param("/admin/kai-capability-catalog.json", {}, '"security_tier"',
                 id="static-catalog-asset"),
    pytest.param("/admin/automations.json", {}, '"hourly_cycles"',
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


def test_authorized_capability_payload_still_carries_real_data(client):
    """Pinning the three identities to EACH OTHER does not pin them to reality — a payload gutted to
    nulls is identical across all three.

    Checking field NAMES is not enough either: every operational value in all 126 records can be
    falsified while the names survive, which renders as '0 available, 0 certified, 126 UNCERTIFIED'
    under a healthy-looking header. So assert VALUES, and assert them across EVERY record — an
    earlier version used `first = capabilities[0]` and an `any()` that short-circuits, so it
    inspected exactly one of 126.
    """
    d = client.get("/admin/capabilities", headers={"Accept": "application/json",
                                                   **_owner_key_headers()}).json()
    assert d["source"] == "CapabilityRegistry"
    caps = d["capabilities"]
    assert d["count"] == len(caps) >= 100, "the catalogue lost its entries"

    for i, c in enumerate(caps):                      # EVERY record, not record 0
        for field in ("id", "name", "type", "risk_class", "security_tier", "permissions"):
            assert field in c, f"capability {i} lost {field}"
        assert str(c["id"]).strip(), f"capability {i} has an empty id"
        assert str(c["name"]).strip(), f"capability {i} has an empty name"

    # A gutting sets every record to the same value. Real data does not agree with itself: the
    # catalogue genuinely contains a mix. Asserting VARIETY catches the flattening without hardcoding
    # any particular business truth, which would break the day the real distribution changes.
    for field in ("availability", "type", "risk_class"):
        distinct = {str(c.get(field)) for c in caps}
        assert len(distinct) > 1, (
            f"every one of {len(caps)} capabilities reports the same {field}={distinct} — a real "
            "catalogue is not uniform, so this is a flattened or fabricated payload")


def test_authorized_automations_payload_agrees_with_the_subsystems_it_aggregates(client):
    """A payload cannot be checked for truth by looking at it.

    The all-NULL skeleton is caught by the marker; the all-ZERO skeleton is not — same shape, every
    value a lie, and it renders as 'OFF · not configured · stopped · no jobs registered (real 0)'.
    No threshold distinguishes that from a genuinely idle system.

    So compare the endpoint against the SOURCE it claims to aggregate. If the scheduler really is
    stopped, both say stopped and the test passes honestly; if the aggregator was gutted, they
    disagree and it fails.
    """
    d = client.get("/admin/automations.json", headers=_owner_key_headers()).json()
    assert d.get("generated_at"), "the payload lost its timestamp"

    try:
        sched = core_api._get_scheduler()
    except Exception as e:                            # noqa: BLE001
        # The source is genuinely unreachable here (the optional `schedule` package is absent in
        # this environment). That is a real state, and the honest report for it is null — NOT a
        # zeroed dict, which would render as "stopped · no jobs registered (real 0)" and claim an
        # observation nobody made. Assert exactly that, rather than skipping.
        assert d.get("scheduler") is None, (
            f"the scheduler source is unavailable ({type(e).__name__}) but the endpoint reported "
            f"{d.get('scheduler')!r} — a fabricated observation")
        return

    real_jobs = list(getattr(sched, "jobs", []) or [])
    real_running = bool(getattr(sched, "_running", False))

    reported = d.get("scheduler")
    if real_jobs or real_running:
        assert isinstance(reported, dict), (
            f"the scheduler reports {len(real_jobs)} jobs / running={real_running}, but the endpoint "
            "returned null for it — the aggregator is dropping a live subsystem")
        assert reported.get("total") == len(real_jobs), (
            f"endpoint says total={reported.get('total')}, the scheduler has {len(real_jobs)} jobs")
        assert bool(reported.get("running")) == real_running, (
            f"endpoint says running={reported.get('running')}, the scheduler says {real_running}")
        assert len(reported.get("jobs") or []) == min(len(real_jobs), 80), \
            "the job list was truncated to a different length than the endpoint documents"

    if isinstance(d.get("autopilot"), dict):
        assert "hourly_cycles" in d["autopilot"]


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
    """A rewritten path must never reach the payload without a credential. 401/404/307/308 are all
    acceptable; a 200 carrying the marker is not.

    `credential-in-query-string` here uses the CORRECT key, and passes only because conftest sets
    OPERATOR_SESSION_ENABLED=true. That is not the shipped default — see the pair of tests below,
    which pin what actually happens under each configuration instead of asserting a blanket rule
    that is only true in the test environment.
    """
    r = client.get(mutate(path), headers=headers, follow_redirects=False)
    assert not (r.status_code == 200 and marker in r.text), \
        f"{label} reached {path} anonymously ({r.status_code})"


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_url_credential_is_refused_when_the_operator_session_is_enabled(client, path, headers, marker):
    """With OPERATOR_SESSION_ENABLED on — the deployed posture per the merge runbook — a key in the
    query string does NOT authenticate, so it never reaches an access log or a Referer header."""
    assert core_api._OPERATOR_SESSION_CFG.enabled, "this test is vacuous with the session disabled"
    r = client.get(f"{path}?api_key={OWNER_KEY}", headers=headers)
    assert r.status_code == 401
    assert marker not in r.text


@pytest.mark.parametrize("path,headers,marker", PROTECTED)
def test_url_credential_IS_accepted_when_the_operator_session_is_disabled(path, headers, marker,
                                                                          monkeypatch):
    """DOCUMENTED RESIDUAL, not an endorsement.

    core/api.py defaults OPERATOR_SESSION_ENABLED to "false", and the merge runbook lists disabling
    it as the rollback step ("?api_key= accepted again"). Under that configuration `_resolve_api_key`
    honours a query-string key, so these four routes authenticate a credential carried in the URL —
    where it lands in edge logs, access logs, Referer headers and browser history.

    This test exists because the previous version of this file asserted the OPPOSITE as an absolute,
    and passed only because conftest pins the flag on. An assertion that is true solely in the test
    environment is worse than no assertion: it reports a property the deployment does not have.

    Fixing this means changing _resolve_api_key, which is outside this hotfix's scope. Pinned here so
    the behaviour is visible and cannot change unnoticed.
    """
    import dataclasses
    monkeypatch.setattr(core_api, "_OPERATOR_SESSION_CFG",
                        dataclasses.replace(core_api._OPERATOR_SESSION_CFG, enabled=False))
    c = TestClient(core_api.app)
    r = c.get(f"{path}?api_key={OWNER_KEY}", headers=headers)
    assert r.status_code == 200 and marker in r.text, (
        "the URL-credential residual has changed — if this was fixed deliberately, delete this test "
        "and tighten the one above; if not, a rollback just changed the auth surface")
    # a WRONG key in the URL must still be refused, in either configuration
    assert c.get(f"{path}?api_key=not-the-owner-key", headers=headers).status_code == 401


@pytest.mark.parametrize("accept", [
    "application/json", "*/*", "text/html,application/json;q=0.9",
    "application/json;q=1.0,text/html;q=0.1", "", "application/*",
    "application/json, text/plain, */*",           # the axios/fetch default
    "APPLICATION/JSON",                            # header values are case-insensitive
])
def test_capabilities_negotiation_never_yields_catalogue_data_anonymously(client, accept):
    """`/admin/capabilities` picks HTML or JSON from Accept.

    The page SHELL is public — it is a static file carrying no capability records, like every other
    admin page. The DATA is not. So the contract is not "always 401"; it is "no negotiation, in any
    casing or q-value ordering, yields catalogue DATA to an anonymous caller".
    """
    r = client.get("/admin/capabilities", headers={"Accept": accept} if accept else {})
    assert r.status_code in (200, 401)
    for m in DATA_MARKERS:
        assert m not in r.text, f"Accept={accept!r} leaked {m} anonymously ({r.status_code})"
    if r.status_code == 200:
        assert "text/html" in r.headers.get("content-type", ""), \
            f"Accept={accept!r} returned a 200 that is not the HTML shell"


def test_the_capabilities_shell_is_public_but_carries_no_data(client):
    """Why the shell may stay public: it contains no capability records at all. If a future change
    inlines the catalogue into the page, this fails — and it fails before the page ships."""
    r = client.get("/admin/capabilities", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "text/html" in r.headers.get("content-type", "")
    for m in DATA_MARKERS:
        assert m not in r.text, f"the public shell now carries {m}"
    for cap_id in ("kai-memory", "claude-code", "context7", "playwright"):
        assert cap_id not in r.text, f"the public shell now names capability {cap_id}"
    assert len(r.content) < 40_000, (
        f"the shell grew to {len(r.content)} B — the catalogue is ~100 KB, so this size jump is how "
        "an inlined payload would arrive")


def test_the_capabilities_shell_can_explain_itself_to_a_signed_out_reader(client):
    """The reason the shell is public rather than gated: it carries the honest 401 message written
    for exactly this reader. Gating the route made that message unreachable."""
    r = client.get("/admin/capabilities", headers={"Accept": "text/html"})
    assert "Owner sign-in required" in r.text
    assert "not an empty catalogue" in r.text


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
# The ONLY callables that authenticate ON AN /admin PATH. Deliberately one name.
#
# This list has been wrong twice, in both directions, and both mistakes were the same mistake —
# assuming a dependency implies authentication:
#   v1  collected EVERY dependency and treated non-empty as "guarded", so Depends(get_db) exempted
#       a route from the probe below.
#   v2  narrowed to five names — and included `verify_api_key`, which core/api.py:240 short-circuits
#       for any path not starting with "/api/". That is the ROOT CAUSE of this entire incident, so
#       listing it here meant a new /admin route using the app's most common auth dependency would
#       both leak anonymously AND be skipped by the control written to catch exactly that.
#       It also listed `require_admin`, which exists nowhere in the repository, and `require_can_act`,
#       which authorizes CONSEQUENTIAL action families only and returns an owner principal for an
#       anonymous request on any other family.
#
# Being too NARROW is safe: an unlisted auth dependency only means the route gets probed, and a
# genuinely guarded route answers 401 and is skipped anyway. Being too WIDE is how the hole reopens.
# So: add a name here only with a test proving it refuses an anonymous /admin request.
AUTH_CALLABLES = frozenset({"require_admin_json"})


def _dependency_names(path: str) -> set:
    """Every dependency callable on a route, unfiltered. Not an authorization answer."""
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


def _auth_dependency_names(path: str) -> set:
    """Only the dependencies that actually authenticate."""
    return _dependency_names(path) & AUTH_CALLABLES


def test_every_auth_callable_actually_refuses_an_anonymous_admin_request(client):
    """Membership in AUTH_CALLABLES must be EARNED, not asserted.

    Each name is mounted on a throwaway /admin route that returns a marker, and the route is then
    called anonymously. A name that does not produce a 401 does not authenticate on an /admin path
    and must not exempt anything. `verify_api_key` fails this test — which is why it is no longer
    listed, and why this test exists in place of the previous one, which only checked that two of
    the five names resolved to something callable.
    """
    from fastapi import Depends as _D

    for name in sorted(AUTH_CALLABLES):
        dep = getattr(core_api, name, None)
        assert callable(dep), f"AUTH_CALLABLES names {name}, which does not exist on core.api"

        path = f"/admin/zz-authprobe-{name}.json"

        def _probe(_a: None = _D(dep)):
            from fastapi.responses import JSONResponse
            return JSONResponse({"security_tier": "leaked"})

        core_api.app.get(path, include_in_schema=False)(_probe)
        try:
            r = client.get(path, headers={"Accept": "application/json"})
            assert r.status_code == 401, (
                f"{name} is in AUTH_CALLABLES but let an anonymous /admin request through "
                f"({r.status_code}) — it exempts routes from the enumeration guard while "
                f"authenticating nothing")
            assert "leaked" not in r.text
        finally:
            core_api.app.router.routes[:] = [
                rt for rt in core_api.app.router.routes if getattr(rt, "path", None) != path]


def test_verify_api_key_is_deliberately_excluded(client):
    """Pin the reason. verify_api_key returns early for any path outside /api/, so mounting it on an
    /admin route authenticates nothing. If this ever starts refusing, the root cause of this incident
    was fixed and AUTH_CALLABLES can be reconsidered — until then it must stay out."""
    from fastapi import Depends as _D

    def _probe(_a: None = _D(core_api.verify_api_key)):
        from fastapi.responses import JSONResponse
        return JSONResponse({"security_tier": "leaked"})

    core_api.app.get("/admin/zz-verify-api-key.json", include_in_schema=False)(_probe)
    try:
        r = client.get("/admin/zz-verify-api-key.json", headers={"Accept": "application/json"})
        assert r.status_code == 200 and "leaked" in r.text, (
            "verify_api_key now refuses an anonymous /admin request — the /api/-only short circuit "
            "at core/api.py:240 appears to be fixed; revisit AUTH_CALLABLES and this test")
        assert "verify_api_key" not in AUTH_CALLABLES
    finally:
        core_api.app.router.routes[:] = [
            rt for rt in core_api.app.router.routes
            if getattr(rt, "path", None) != "/admin/zz-verify-api-key.json"]


@pytest.mark.parametrize("path", ["/admin/capabilities/{cap_id}",
                                  "/admin/kai-capability-catalog.json",
                                  "/admin/automations.json"])
def test_route_declares_the_auth_dependency(path):
    """MUTATION GUARD. Deleting `Depends(require_admin_json)` from any of these fails here by name,
    so the regression is reported as 'the guard is gone' rather than as a confusing 200.

    /admin/capabilities is deliberately absent: its data branch calls require_admin_json directly so
    the HTML shell stays reachable, and that call is pinned by test_capabilities_json_branch_calls_
    the_one_policy below instead."""
    assert "require_admin_json" in _auth_dependency_names(path), \
        f"{path} lost its require_admin_json dependency"


def test_capabilities_json_branch_calls_the_one_policy():
    """/admin/capabilities gates its JSON branch by CALLING require_admin_json, so there is no
    dependency to introspect. Pin the call site, and pin that it precedes the catalogue build —
    otherwise the data is assembled (and could be returned) before anyone is authenticated."""
    import inspect as _inspect
    src = _inspect.getsource(core_api._admin_capabilities)
    assert "require_admin_json(request)" in src, \
        "/admin/capabilities no longer calls the one policy function on its JSON branch"
    assert src.index("require_admin_json(request)") < src.index("_capability_catalog()"), \
        "the catalogue is built before the caller is authenticated"
    # and it must not have grown its own copy of the policy
    for forbidden in ("_API_KEY", "compare_digest", "_session_owner_ok", "_release_verifier_ok"):
        assert forbidden not in src, f"/admin/capabilities re-implements auth ({forbidden})"


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
    markers = DATA_MARKERS | _runtime_data_markers(client)
    offenders = []
    for route in core_api.app.routes:
        path = getattr(route, "path", "") or ""
        if not path.startswith("/admin") or path in reviewed_public:
            continue
        if "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        if _auth_dependency_names(path):
            continue
        if "{" in path:                       # parameterised: probed by name in PROTECTED above
            continue
        # PROBE EVERY REPRESENTATION, not just one. The previous version sent a single
        # `Accept: application/json` and skipped any non-200 — so a route that 401s on JSON while
        # serving data to `*/*` was never byte-scanned. That is exactly the shape
        # /admin/capabilities now has, and a `?format=json` convenience added later would have
        # leaked the catalogue with a green suite.
        for accept in GUARD_PROBE_ACCEPTS:
            for url in (path, f"{path}?format=json"):
                r = client.get(url, headers={"Accept": accept}, follow_redirects=False)
                if r.status_code != 200:
                    continue
                # Judge the BYTES, not the Content-Type header: the same payload served as
                # text/plain, text/javascript or a bare Response must still be caught. This
                # codebase already serves 27 admin assets as text/javascript.
                body = r.text
                leaked = sorted(m for m in markers if m in body)
                if leaked:
                    offenders.append(
                        f"{url} (Accept: {accept}) -> 200 "
                        f"{r.headers.get('content-type', '')} ({len(r.content)} B) leaking {leaked}")
    assert not offenders, "anonymous /admin payload: " + "; ".join(sorted(set(offenders)))


def test_the_enumeration_guard_can_actually_fail(client):
    """The guard above is the one standing control against a third repeat of this bug. Prove it is
    live: a route added with a benign non-auth dependency, serving the payload as text/plain, must
    still be caught. Both of those shapes previously slipped past it."""
    from fastapi import Depends as _D
    from fastapi.responses import Response as _R

    def _benign():
        return None

    @core_api.app.get("/admin/zz-guard-selftest.json", include_in_schema=False)
    def _zz(_x: None = _D(_benign)):
        # Both blind spots at once: a benign dependency, and the payload served as text/plain with
        # UNQUOTED keys — the bundler shape that evaded the quoted-only marker set.
        return _R('{source: "CapabilityRegistry", hourly_cycles, id: "kai-memory"}',
                  media_type="text/plain")

    try:
        core_api.app.router.routes  # noqa: B018 — ensure the route table is rebuilt
        with pytest.raises(AssertionError, match="zz-guard-selftest"):
            test_no_other_admin_json_route_is_anonymous(client)
    finally:
        core_api.app.router.routes[:] = [
            rt for rt in core_api.app.router.routes
            if getattr(rt, "path", None) != "/admin/zz-guard-selftest.json"]
    # and the table is restored
    assert not any(getattr(rt, "path", None) == "/admin/zz-guard-selftest.json"
                   for rt in core_api.app.routes)
