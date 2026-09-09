"""The NarAI scheduler is not a public API.

INCIDENT, 2026-09-08. `/api/narai/schedules` and its subtree answered ANONYMOUS callers on
production. It is not only a read leak — the subtree carries two consequential routes:

    GET   /api/narai/schedules              list: id, name, description, category, frequency,
                                            day, time, enabled, last_run, last_status, run_count,
                                            next_run, trigger_fn (an internal Python path)
    GET   /api/narai/schedules/stats        totals
    PATCH /api/narai/schedules/{id}         enable/disable a schedule, change its run time
    POST  /api/narai/schedules/{id}/trigger RUN A JOB NOW

Measured anonymously on production: the list returned 200 with 17 schedules including trigger_fn
and exact next_run timestamps.

TWO INDEPENDENT EXEMPTIONS caused it, which is why fixing one would have looked like a fix:

  1. `_PUBLIC_PATHS.add("/api/narai/schedules")` — an EXACT-path entry, exempting the list.
  2. `_PUBLIC_PREFIXES` contained "/api/narai/schedules" WITHOUT a trailing slash, and the middleware
     tests it with `path.startswith(...)`. That exempted the entire subtree — including PATCH and
     the trigger. The neighbouring entries in that tuple all end in "/"; this one did not.

CONTAINMENT reuses the existing boundary rather than inventing one. With both exemptions removed the
routes fall under `api_key_middleware`, which is already owner-only: the owner API key by header, or
a valid owner session cookie. A release verifier is not part of the `/api/` policy on App A and is
therefore refused on all four — deliberately not extended during an incident. Mutating routes carry
an additional explicit refusal so that if `/api/` ever starts accepting a verifier, consequential
actions stay closed.
"""
import os

import pytest
from fastapi.testclient import TestClient

from core import api as core_api                          # noqa: E402
from core import operator_session as osess                # noqa: E402
from core.operator_session_web import COOKIE_NAME         # noqa: E402

os.environ.setdefault("RELEASE_VERIFIER_SIGNING_SECRET", "verifier-signing-secret")

OWNER_KEY = os.environ["API_KEY"]
SESSION_SECRET = os.environ["SESSION_SIGNING_SECRET"]

READ_ROUTES = ["/api/narai/schedules", "/api/narai/schedules/stats"]
# (method, path) — every consequential route in the subtree.
WRITE_ROUTES = [
    ("PATCH", "/api/narai/schedules/market_intel"),
    ("POST", "/api/narai/schedules/market_intel/trigger"),
]
# A deliberately non-existent id: if a guard ever fails open, the handler answers 404/400 for an
# unknown schedule rather than dispatching a real job. No production job is ever triggered by tests.
SAFE_ID = "__incident_suite_nonexistent__"


@pytest.fixture
def client():
    return TestClient(core_api.app)


def _owner_key():
    return {"X-API-Key": OWNER_KEY}


def _owner_session():
    return {COOKIE_NAME: osess.mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)}


def _verifier():
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    return {VERIFIER_HEADER: mint_verifier_token(subject="incident", secret=os.environ[
        "RELEASE_VERIFIER_SIGNING_SECRET"])}


UNAUTHORIZED = {
    "anonymous": ({}, {}),
    "bad-key": ({"X-API-Key": "not-the-owner-key"}, {}),
    "operator-session": ({}, {COOKIE_NAME: osess.mint_session(
        "operator", secret=SESSION_SECRET, ttl_seconds=3600)}),
    "viewer-session": ({}, {COOKIE_NAME: osess.mint_session(
        "viewer", secret=SESSION_SECRET, ttl_seconds=3600)}),
    "signed-out": ({}, {COOKIE_NAME: ""}),
    "garbage-cookie": ({}, {COOKIE_NAME: "not.a.session"}),
    "foreign-secret-session": ({}, {COOKIE_NAME: osess.mint_session(
        "owner", secret="a-different-signing-secret", ttl_seconds=3600)}),
    "forged-verifier": ({"x-kai-verifier-token": "Zm9yZ2Vk.Zm9yZ2Vk"}, {}),
}


# ── reads ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", READ_ROUTES)
@pytest.mark.parametrize("label", sorted(UNAUTHORIZED))
def test_unauthorized_cannot_read_the_schedule_inventory(client, path, label):
    headers, cookies = UNAUTHORIZED[label]
    r = client.get(path, headers=headers, cookies=cookies)
    assert r.status_code == 401, f"{label} read {path} ({r.status_code})"
    assert "trigger_fn" not in r.text and "next_run" not in r.text


@pytest.mark.parametrize("path", READ_ROUTES)
def test_the_release_verifier_cannot_read_the_scheduler(client, path):
    """Deliberate: the verifier's scope on App A is `require_admin_json` for /admin JSON. Extending
    it onto the /api surface during an incident would be broadening authority, not containing it."""
    r = client.get(path, headers=_verifier())
    assert r.status_code == 401


@pytest.mark.parametrize("path", READ_ROUTES)
def test_owner_can_still_read(client, path):
    assert client.get(path, headers=_owner_key()).status_code == 200
    assert client.get(path, cookies=_owner_session()).status_code == 200


# ── writes and execution ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("method,path", WRITE_ROUTES)
@pytest.mark.parametrize("label", sorted(UNAUTHORIZED))
def test_unauthorized_cannot_mutate_or_trigger(client, method, path, label):
    headers, cookies = UNAUTHORIZED[label]
    r = client.request(method, path, headers=headers, cookies=cookies,
                       json={"enabled": False, "time": "23:59"})
    assert r.status_code == 401, (
        f"{label} reached {method} {path} ({r.status_code}) — an unauthorized caller can change or "
        "run the business's automations")


@pytest.mark.parametrize("method,path", WRITE_ROUTES)
def test_the_release_verifier_cannot_mutate_or_trigger(client, method, path):
    r = client.request(method, path, headers=_verifier(), json={"enabled": False})
    assert r.status_code in (401, 403), "a read-only verifier reached a consequential route"


def test_the_consequential_guard_refuses_a_verifier_on_its_own():
    """Through the app this guard is masked: api_key_middleware rejects a verifier before the
    dependency runs, so deleting the guard changes no status code and a route-level test cannot
    tell. That is precisely why it needs a direct test — otherwise it is dead weight a future
    reader deletes, and the day /api starts accepting verifiers (the role exists to read protected
    surfaces) enabling a schedule and running a job would come with it.

    Exercised against the function itself, with a real signed verifier token.
    """
    from fastapi import HTTPException
    from starlette.requests import Request as _Req
    from app.services.holding.verifier_role import VERIFIER_HEADER

    tok = _verifier()[VERIFIER_HEADER].encode()
    scope = {"type": "http", "method": "PATCH", "path": "/api/narai/schedules/x",
             "headers": [(VERIFIER_HEADER.encode(), tok)], "query_string": b""}
    with pytest.raises(HTTPException) as ei:
        core_api._refuse_verifier_on_consequential_action(_Req(scope))
    assert ei.value.status_code == 403
    assert "read-only" in str(ei.value.detail)

    # and it does not refuse a caller who is NOT a verifier — it must not become a blanket deny
    plain = {"type": "http", "method": "PATCH", "path": "/api/narai/schedules/x",
             "headers": [], "query_string": b""}
    core_api._refuse_verifier_on_consequential_action(_Req(plain))


def test_both_consequential_routes_declare_the_guard():
    """Mutation guard: the dependency must stay attached to BOTH mutating routes."""
    guarded = set()
    for route in core_api.app.routes:
        path = getattr(route, "path", "") or ""
        if not path.startswith("/api/narai/schedules"):
            continue
        deps = getattr(getattr(route, "dependant", None), "dependencies", []) or []
        names = {getattr(getattr(d, "call", None), "__name__", "") for d in deps}
        if "_refuse_verifier_on_consequential_action" in names:
            guarded.add((tuple(sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})), path))
    assert guarded == {
        (("PATCH",), "/api/narai/schedules/{schedule_id}"),
        (("POST",), "/api/narai/schedules/{schedule_id}/trigger"),
    }, f"consequential guard is not on both mutating routes: {guarded}"


def test_an_unauthorized_trigger_never_reaches_the_dispatcher(client, monkeypatch):
    """Status codes alone do not prove nothing ran. Trip a wire on the dispatcher itself."""
    from core import narai_scheduler
    fired = []
    monkeypatch.setattr(narai_scheduler, "trigger_schedule",
                        lambda sid: fired.append(sid) or {"success": True})
    for label, (headers, cookies) in UNAUTHORIZED.items():
        client.post(f"/api/narai/schedules/{SAFE_ID}/trigger", headers=headers, cookies=cookies)
    assert fired == [], f"unauthorized callers dispatched: {fired}"


def test_an_unauthorized_patch_never_reaches_the_writer(client, monkeypatch):
    from core import narai_scheduler
    wrote = []
    monkeypatch.setattr(narai_scheduler, "update_schedule",
                        lambda sid, **kw: wrote.append((sid, kw)) or {"id": sid})
    for label, (headers, cookies) in UNAUTHORIZED.items():
        client.patch(f"/api/narai/schedules/{SAFE_ID}", headers=headers, cookies=cookies,
                     json={"enabled": False, "time": "03:00"})
    assert wrote == [], f"unauthorized callers wrote: {wrote}"


# ── no alternate shape reopens it ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mutate,label", [
    (lambda p: p + "/", "trailing-slash"),
    (lambda p: p + "?x=1", "query-string"),
    (lambda p: p.replace("/api/", "/./api/", 1), "dot-segment"),
    (lambda p: p.replace("/api/", "//api/", 1), "double-slash"),
    (lambda p: p + "?api_key=" + OWNER_KEY, "credential-in-query-string"),
])
def test_no_path_shape_reopens_anonymous_read(client, mutate, label):
    r = client.get(mutate("/api/narai/schedules"), follow_redirects=False)
    assert not (r.status_code == 200 and "trigger_fn" in r.text), \
        f"{label} reopened anonymous read ({r.status_code})"


@pytest.mark.parametrize("override", ["X-HTTP-Method-Override", "X-Method-Override"])
def test_method_override_headers_do_not_reach_a_mutation(client, override):
    """A GET carrying a method-override header must not become a PATCH or a trigger."""
    r = client.get("/api/narai/schedules", headers={override: "PATCH"})
    assert r.status_code == 401


def test_the_prefix_exemption_is_gone_and_the_neighbours_are_intact():
    """MUTATION GUARD on the original defect, updated for the model that replaced it.

    The exemption used to be a tuple of string prefixes tested with startswith(), so
    "/api/narai/schedules" without a trailing slash exempted the whole subtree — PATCH and trigger
    included. That tuple is gone. Public access is now an explicit PublicRule table matched exactly,
    or by descendant with a "/" boundary, so a character-prefix exemption cannot be expressed at all.

    This asserts the scheduler is absent from the table, that the shape which caused the defect is
    structurally impossible, and that the withdrawn action exemptions have not crept back."""
    rules = core_api.PUBLIC_API_RULES
    assert rules, "the public rule table is empty — the guard would pass vacuously"

    paths = {r.path for r in rules}
    assert "/api/narai/schedules" not in paths, "the scheduler exemption is back"

    # the exemptions withdrawn because they were unauthorized ACTION paths
    for withdrawn in ("/api/narai/run", "/api/narai/revenue", "/api/store/redeliver"):
        assert withdrawn not in paths, f"{withdrawn} was re-added as a public rule"

    # and no rule may match a scheduler path, by any spelling
    for spelling in ("/api/narai/schedules", "/api/narai/schedules/stats",
                     "/api/narai/schedules/x", "//api/narai/schedules"):
        for method in ("GET", "POST", "PATCH", "DELETE"):
            assert core_api._public_rule_for(spelling, method) is None, \
                f"{method} {spelling} matched a public rule"

    # the defect's shape cannot be written any more: intent lives in a boolean, not in a string
    for r in rules:
        assert not r.path.endswith("/"), \
            f"{r.path} encodes subtree intent in the string; use descendants=True"
        assert isinstance(r.descendants, bool)
        assert r.methods, f"{r.path} permits no method"
        assert r.purpose and len(r.purpose) > 20, f"{r.path} has no documented purpose"


def test_the_exact_path_exemption_is_gone():
    assert "/api/narai/schedules" not in core_api._PUBLIC_PATHS, \
        "the scheduler is still in _PUBLIC_PATHS"


# ── honest unavailability ─────────────────────────────────────────────────────────────────────────
def test_unreadable_state_reports_unavailable_not_a_fabricated_idle_scheduler(client, monkeypatch,
                                                                              tmp_path):
    """`_load()` swallowed read errors and returned {}, so a corrupt or unreadable state file
    rendered as every schedule `run_count: 0, last_status: "never"` — an observation nobody made.
    An unreadable source must say so.

    HERMETIC. An earlier version depended on data/narai_schedules.json existing in the checkout:
    where it did not, _load() short-circuited on the exists() check, never reached the patched
    reader, and reported ABSENT — so the test passed or failed by accident of the working tree."""
    from core import narai_scheduler

    state = tmp_path / "narai_schedules.json"
    state.write_text("[]")
    monkeypatch.setattr(narai_scheduler, "SCHEDULES_FILE", state)

    def _boom():
        raise OSError("state file unreadable")

    monkeypatch.setattr(narai_scheduler, "_read_state_file", _boom)
    r = client.get("/api/narai/schedules", headers=_owner_key())
    assert r.status_code == 200
    d = r.json()
    assert d.get("state") == "UNAVAILABLE", (
        "an unreadable state file was reported as a healthy scheduler; "
        f"state={d.get('state')!r}")
    for s in d.get("schedules", []):
        assert s.get("last_status") == "UNAVAILABLE", \
            "a schedule reported a runtime status that could not be read"
        assert s.get("run_count") == "UNAVAILABLE", \
            "a schedule reported run_count 0 while the state file was unreadable"


def test_readable_state_reports_ok(client, monkeypatch, tmp_path):
    """Also hermetic: a present, readable state file must report OK. Previously this asserted OK
    while depending on the checkout to supply the file, so it reported ABSENT on a clean tree."""
    from core import narai_scheduler
    state = tmp_path / "narai_schedules.json"
    state.write_text("[]")
    monkeypatch.setattr(narai_scheduler, "SCHEDULES_FILE", state)
    d = client.get("/api/narai/schedules", headers=_owner_key()).json()
    assert d.get("state") == "OK"
    assert isinstance(d.get("schedules"), list)


def test_absent_state_file_is_reported_as_absent_not_unavailable(client, monkeypatch, tmp_path):
    """The third state, and the reason the other two needed pinning: a first run with no state file
    is ABSENT — legitimately nothing has executed yet — and must not be confused with UNAVAILABLE,
    which means the file exists and could not be read."""
    from core import narai_scheduler
    monkeypatch.setattr(narai_scheduler, "SCHEDULES_FILE", tmp_path / "does-not-exist.json")
    d = client.get("/api/narai/schedules", headers=_owner_key()).json()
    assert d.get("state") == "ABSENT"
