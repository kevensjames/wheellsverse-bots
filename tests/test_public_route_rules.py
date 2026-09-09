"""Public-route authorization is an explicit rule table, never a `startswith()` prefix.

THE DEFECT. `api_key_middleware` decided public access with:

    if path.startswith("/api/") and not any(path.startswith(p) for p in _PUBLIC_API_PREFIXES)

A prefix is not a path. `"/api/narai/run"` in that tuple exempted every route whose path merely
BEGINS with those characters — so `POST /api/narai/run_bot`, a route nobody exempted on purpose, was
anonymous. Measured with the gate live:

    POST /api/narai/run_bot   -> 200, and the handler RAN (loaded 138 bots, attempted a trigger)
    POST /api/narai/revenue   -> 200, and the handler RAN (RevenueLoop executed)

`/api/narai/run` is not a customer inference endpoint either: its own docstring says it "Run[s] one
full NarAI autonomous cycle in the background — State → Goal → Plan → Execute → Evaluate → Learn."
An anonymous caller could start the autonomous operator.

Confirmed exempt on production with a probe that cannot execute anything — a POST to a NON-EXISTENT
path under each prefix, where 401 means the gate stopped it and 404 means routing was reached:

    POST /api/narai/run_probe_nonexistent       -> 404  EXEMPT
    POST /api/narai/revenue_probe_nonexistent   -> 404  EXEMPT
    POST /api/narai/status_probe_nonexistent    -> 404  EXEMPT
    POST /api/store/redeliver_probe_nonexistent -> 404  EXEMPT
    POST /api/scheduler/jobs_probe_nonexistent  -> 401  gated (control)

THE MODEL. Every public exception is now a PublicRule with four explicit fields — exact normalized
path, permitted methods, whether descendants are included, and a documented purpose. A rule for
`/api/narai/run` cannot match `/api/narai/run_bot`, because matching is exact or descendant-with-a-
separator, never a character prefix.

No test here invokes a real action handler. Reachability is proven with spies that assert the
handler was never entered, and with non-existent descendants that cannot execute anything.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")
os.environ.setdefault("RELEASE_VERIFIER_SIGNING_SECRET", "verifier-signing-secret")

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

OWNER_KEY = os.environ["API_KEY"]
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]

# Routes that EXECUTE something. None may be reachable without an owner.
ACTION_ROUTES = [
    ("POST", "/api/narai/run"),          # runs a full autonomous cycle
    ("POST", "/api/narai/run_bot"),      # runs a bot — the missing-slash victim
    ("POST", "/api/narai/revenue"),      # runs the revenue loop
    ("GET", "/api/store/redeliver"),     # re-sends a paid order's files (an email-send action)
]

ALL_METHODS = ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]


@pytest.fixture
def client():
    return TestClient(core_api.app)


@pytest.fixture(autouse=True)
def _prod_env(monkeypatch):
    """Hosted posture, so the gate is live for every check in this file."""
    monkeypatch.setattr(core_api, "_APP_ENV", "production", raising=False)


def _owner():
    return {"X-API-Key": OWNER_KEY}


def _verifier():
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    return {VERIFIER_HEADER: mint_verifier_token(
        subject="rules", secret=os.environ["RELEASE_VERIFIER_SIGNING_SECRET"])}


UNAUTHORIZED = {
    "anonymous": ({}, {}),
    "bad-key": ({"X-API-Key": "nope"}, {}),
    "operator-session": ({}, {COOKIE_NAME: osess.mint_session("operator", secret=SESSION_SECRET,
                                                              ttl_seconds=3600)}),
    "viewer-session": ({}, {COOKIE_NAME: osess.mint_session("viewer", secret=SESSION_SECRET,
                                                            ttl_seconds=3600)}),
    "signed-out": ({}, {COOKIE_NAME: ""}),
    "garbage-cookie": ({}, {COOKIE_NAME: "not.a.session"}),
    "foreign-secret": ({}, {COOKIE_NAME: osess.mint_session("owner", secret="other",
                                                            ttl_seconds=3600)}),
    "forged-verifier": ({"x-kai-verifier-token": "Zm9yZ2Vk.Zm9yZ2Vk"}, {}),
    "expired-verifier": ({}, {}),   # filled in below
}


# ── 1. no unauthorized identity reaches an action ─────────────────────────────────────────────────
@pytest.mark.parametrize("method,path", ACTION_ROUTES)
@pytest.mark.parametrize("label", sorted(UNAUTHORIZED))
def test_no_unauthorized_identity_reaches_an_action_route(client, method, path, label):
    headers, cookies = UNAUTHORIZED[label]
    r = client.request(method, path, headers=headers, cookies=cookies, json={})
    assert r.status_code == 401, f"{label} reached {method} {path} ({r.status_code})"


@pytest.mark.parametrize("method,path", ACTION_ROUTES)
def test_the_release_verifier_cannot_run_anything(client, method, path):
    """Read-only means read-only: no bot, no revenue loop, no redelivery."""
    r = client.request(method, path, headers=_verifier(), json={})
    assert r.status_code in (401, 403), f"a verifier reached {method} {path}"


# ── 2. THE HANDLER MUST NEVER BE ENTERED ──────────────────────────────────────────────────────────
def test_no_action_handler_is_entered_by_an_unauthorized_caller(client, monkeypatch):
    """A status code is not proof that nothing ran. Spy on every underlying action and assert the
    spies were never called — no bot load, no revenue loop, no redelivery, no subprocess."""
    calls = []

    import core.narai_core as _nc
    monkeypatch.setattr(_nc, "get_narai_core",
                        lambda *a, **k: calls.append("narai_core") or (_ for _ in ()).throw(
                            AssertionError("get_narai_core entered")), raising=False)
    for mod, name in (("core.api", "_get_narai"),):
        if hasattr(core_api, name):
            monkeypatch.setattr(core_api, name,
                                lambda *a, **k: calls.append(name), raising=False)

    for label, (headers, cookies) in UNAUTHORIZED.items():
        for method, path in ACTION_ROUTES:
            client.request(method, path, headers=headers, cookies=cookies, json={})
    assert calls == [], f"an unauthorized request entered a handler: {calls}"


def test_no_subprocess_or_outbound_call_from_an_unauthorized_request(client, monkeypatch):
    """Belt and braces: nothing may shell out or open a socket on a refused request."""
    import subprocess, urllib.request
    fired = []
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: fired.append("Popen"), raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fired.append("run"), raising=False)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: fired.append("urlopen"), raising=False)
    for method, path in ACTION_ROUTES:
        client.request(method, path, json={})
    assert fired == [], f"a refused request still caused: {fired}"


# ── 3. the exact-vs-prefix collision, in both directions ──────────────────────────────────────────
def test_a_public_rule_for_run_does_not_match_run_bot():
    """THE defect, asserted at the matcher rather than through the app."""
    match = core_api._public_rule_for
    assert match("/api/narai/run_bot", "POST") is None, \
        "a rule matched /api/narai/run_bot — prefix matching is back"
    assert match("/api/narai/revenue_probe", "POST") is None
    assert match("/api/narai/status_probe", "GET") is None
    assert match("/api/store/redeliver_probe", "GET") is None


@pytest.mark.parametrize("suffix", ["_bot", "_probe_nonexistent", "x", "-extra", ".json"])
@pytest.mark.parametrize("base", ["/api/narai/run", "/api/narai/revenue", "/api/narai/status",
                                  "/api/store/redeliver"])
def test_sibling_names_are_never_public(client, base, suffix):
    """A non-existent descendant must reach authentication BEFORE routing: 401, not an exempt 404."""
    r = client.post(f"{base}{suffix}", json={})
    assert r.status_code == 401, f"{base}{suffix} answered {r.status_code} — it was exempted"


@pytest.mark.parametrize("path", ["/api/narai/status/sub", "/api/store/redeliver/sub",
                                  "/api/narai/run/sub"])
def test_descendants_of_exact_rules_are_gated(client, path):
    assert client.get(path).status_code == 401
    assert client.post(path, json={}).status_code == 401


# ── 3b. THE MATCHER ITSELF ────────────────────────────────────────────────────────────────────────
# Asserting only through the app is not enough: FastAPI answers 405 for an unrouted method and
# normalises `//` and `/./` before the app sees them, so both a dropped method check and a removed
# path normalisation SURVIVED as mutants when tested that way. These exercise the matcher directly.

def test_the_method_check_is_real(client):
    """A GET-only rule must not match any other method — proven at the matcher, where FastAPI's
    405-for-an-unrouted-method cannot stand in for the guard."""
    match = core_api._public_rule_for
    assert match("/api/narai/status", "GET") is not None
    for m in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "get", ""):
        assert match("/api/narai/status", m) is None, \
            f"a GET-only public rule matched {m!r} — the method check is not enforced"


def test_method_matching_is_case_correct():
    """Lowercase must not slip through as a different method."""
    match = core_api._public_rule_for
    assert match("/api/narai/status", "get") is None      # not normalised up: exact HTTP verbs only
    assert match("/api/narai/status", "GET") is not None


@pytest.mark.parametrize("raw,expected", [
    ("/api/narai/status", "/api/narai/status"),
    ("//api//narai//status", "/api/narai/status"),
    ("/api/./narai/status", "/api/narai/status"),
    ("/api/narai/x/../status", "/api/narai/status"),
    ("/api/narai/status/", "/api/narai/status"),
    ("/api/narai/status/./", "/api/narai/status"),
    ("/", "/"),
    ("", "/"),
])
def test_path_normalisation(raw, expected):
    assert core_api._norm_path(raw) == expected


@pytest.mark.parametrize("raw", [
    "//api/narai/run_bot", "/api//narai/run_bot", "/api/narai/./run_bot",
    "/api/narai/x/../run_bot", "/api/narai/run_bot/", "/api/narai/run/../run_bot",
])
def test_no_normalised_shape_makes_an_action_public(raw):
    """Every rewritten spelling of an action path must still be unmatched by the rule table."""
    assert core_api._public_rule_for(raw, "POST") is None, f"{raw} matched a public rule"


def test_percent_encoded_separators_are_not_treated_as_separators():
    """%2F is not a path separator. Decoding it here would let a caller forge a shorter path than
    the router will actually use, and match a rule the real request never hits."""
    assert core_api._public_rule_for("/api/narai%2Frun_bot", "POST") is None
    assert core_api._public_rule_for("/api%2Fnarai/status", "GET") is None


def test_dot_dot_cannot_escape_upward_into_a_rule():
    assert core_api._public_rule_for("/api/narai/status/../run_bot", "POST") is None
    assert core_api._public_rule_for("/api/../api/narai/run_bot", "POST") is None


def test_descendant_matching_requires_a_separator():
    """`/api/nx` is a descendant rule; `/api/nxevil` is a different path, not a child."""
    match = core_api._public_rule_for
    assert match("/api/nx/register", "POST") is not None
    assert match("/api/nx", "POST") is not None
    assert match("/api/nxevil", "POST") is None, "descendant matching fell back to a substring"
    assert match("/api/nx-other/thing", "POST") is None


# ── 4. method discipline ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("method", [m for m in ALL_METHODS if m != "GET"])
def test_non_get_methods_on_a_get_only_public_rule_are_gated(client, method):
    """/api/narai/status is GET-only public. Every other method must be refused."""
    r = client.request(method, "/api/narai/status", json={})
    assert r.status_code in (401, 405), f"{method} /api/narai/status -> {r.status_code}"


def test_head_on_a_get_only_rule_leaks_nothing(client):
    r = client.head("/api/narai/status")
    assert r.status_code in (200, 401, 405)
    assert "mood" not in r.text and "skills" not in r.text


@pytest.mark.parametrize("override", ["X-HTTP-Method-Override", "X-Method-Override"])
def test_method_override_headers_cannot_promote_a_request(client, override):
    r = client.get("/api/narai/status", headers={override: "POST"})
    assert r.status_code in (200, 401)      # never routed as a POST action
    r2 = client.get("/api/narai/run", headers={override: "POST"})
    assert r2.status_code == 401


# ── 5. path-shape normalisation ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("shape", [
    "/api/narai/run_bot", "//api/narai/run_bot", "/api//narai/run_bot",
    "/api/narai/./run_bot", "/api/narai/x/../run_bot", "/api/narai/run_bot/",
    "/api/narai/run_bot?x=1", "/API/NARAI/RUN_BOT", "/api/narai/run%5Fbot",
    "/api/narai%2Frun_bot",
])
def test_no_path_shape_makes_an_action_public(client, shape):
    r = client.post(shape, json={}, follow_redirects=False)
    assert r.status_code != 200, f"{shape} reached a handler ({r.status_code})"
    assert r.status_code in (401, 404, 307, 308, 405), f"{shape} -> {r.status_code}"


# ── 6. intended public behaviour still works ──────────────────────────────────────────────────────
def test_the_documented_public_subtrees_are_still_public(client):
    """Every remaining exemption keeps its documented purpose. These carry their own auth (Bearer,
    JWT, signed token, OAuth state) and must not be broken by this change."""
    for rule in core_api.PUBLIC_API_RULES:
        assert rule.purpose and len(rule.purpose) > 20, \
            f"{rule.path} has no documented public purpose"
        assert rule.methods, f"{rule.path} permits no method"


def test_every_public_rule_is_exact_or_explicitly_descendant():
    for rule in core_api.PUBLIC_API_RULES:
        assert rule.path.startswith("/api/")
        assert not rule.path.endswith("/"), \
            f"{rule.path} ends in '/' — encode subtree intent in `descendants`, not in the string"
        assert isinstance(rule.descendants, bool)


def test_narai_status_is_public_get_only_and_bounded(client):
    """App B's holding entity_status probes this with a plain urlopen and NO credentials
    (backend/app/services/holding/entity_status.py), so it is a real unauthenticated health
    consumer and cannot simply be gated. It is therefore REDUCED to a bounded status contract."""
    r = client.get("/api/narai/status")
    assert r.status_code == 200
    d = r.json()
    for leaked in ("mood", "mind", "skills", "env", "last_report_summary", "thought"):
        assert leaked not in d, f"/api/narai/status still exposes internal state: {leaked}"
    assert set(d) <= {"name", "category", "status", "online", "posts", "videos", "images",
                      "last_run", "run_count"}, f"unexpected keys: {sorted(d)}"
    assert len(r.content) < 1024


def test_the_holding_probe_still_gets_what_it_reads(client):
    """entity_status reads these keys; the reduction must not break the health probe."""
    d = client.get("/api/narai/status").json()
    assert "status" in d
