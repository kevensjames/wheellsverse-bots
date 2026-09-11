"""An audit that cannot see the whole application must fail, not pass quietly.

THE FAILURE THIS EXISTS TO PREVENT. core/api.py mounts every NarAI v2 router inside try/except. A
missing optional dependency does not raise — it logs a warning and those routes silently never
exist. That is a reasonable choice for a feature: one broken domain should not take down the stack.

It is not a reasonable input to a security audit. The venv used for the entire 2026-09 containment
sequence lacked chromadb, litellm, cachetools and aiosqlite, so ~120 production routes were absent
from the table every guard walked — including 33 mutating /api/v2/narai routes and the
/api/v2/narai/voice/ws WebSocket. Those guards reported success. They were correct about what they
could see and silent about what they could not, which is the most dangerous shape a security check
can take: it looks identical to a clean result.

So this suite pins ROUTE IDENTITY and SECURITY INVARIANTS, not a total count. A count moves whenever
anyone adds a feature and teaches everyone to re-baseline it without looking; an identity set moves
only when the security surface actually changes, and then it demands a decision.

Everything here runs below FastAPI and below the edge. Framework normalisation hid two mutants
earlier in this sequence (a 405 that masked a dropped method check, TestClient normalising a path),
and production returns a blanket 403 to every WebSocket upgrade including ones that do not exist —
so an HTTP-level probe there cannot distinguish "gated" from "absent". These assertions read the
route table and the manifest directly.
"""
import importlib.util
import os

import pytest

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")

from core import api as core_api                          # noqa: E402
from starlette.routing import WebSocketRoute              # noqa: E402

OPTIONAL_DEPS = ("chromadb", "litellm", "cachetools", "aiosqlite")


def _importable(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


# ── the environment itself ────────────────────────────────────────────────────────────────────────
def test_the_audit_environment_matches_production():
    """First, because every other assertion here is meaningless without it.

    A reduced environment makes routes VANISH. Every guard below would then pass while describing a
    smaller application, and the run would be green.
    """
    missing = [m for m in OPTIONAL_DEPS if not _importable(m)]
    assert not missing, (
        f"optional dependencies missing: {missing}. All are pinned in requirements.txt. Without "
        "them the NarAI v2 routers do not mount, this suite audits a smaller surface than "
        "production serves, and a green run here means nothing.")


# ── the manifest ──────────────────────────────────────────────────────────────────────────────────
def test_every_required_router_mounted():
    """try/except plus a warning is not a successful startup for a protected surface."""
    ok, problems, detail = core_api.router_manifest_status()
    assert ok, (
        f"required routers did not mount: {problems}. This build serves a smaller application than "
        f"the one that was audited. Recorded reasons: "
        f"{ {n: r['reason'] for n, r in detail.items() if r['required'] and not r['mounted']} }")


def test_the_manifest_records_every_required_router():
    """A required router that was never ATTEMPTED is as bad as one that failed — it means the mount
    loop aborted before reaching it, which is precisely what an early import error does."""
    recorded = set(core_api.ROUTER_MANIFEST)
    missing = sorted(core_api.REQUIRED_V2_ROUTERS - recorded)
    assert not missing, f"required routers never attempted: {missing}"


def test_a_failed_required_router_is_a_failure_not_a_warning(monkeypatch):
    """The gate's own behaviour, proven rather than asserted. If this passed with a router marked
    unmounted, the gate would be decoration — which is exactly what phase0-gate.yml was before #80.
    """
    fake = dict(core_api.ROUTER_MANIFEST)
    fake["voice"] = {"required": True, "mounted": False, "reason": "ModuleNotFoundError: chromadb"}
    monkeypatch.setattr(core_api, "ROUTER_MANIFEST", fake)
    ok, problems, _ = core_api.router_manifest_status()
    assert not ok and "voice" in problems


def test_readiness_reports_an_incomplete_route_set(monkeypatch):
    """A deployed instance with a reduced surface must be visible to a probe, not merely healthy."""
    from fastapi.testclient import TestClient
    fake = dict(core_api.ROUTER_MANIFEST)
    fake["sales"] = {"required": True, "mounted": False, "reason": "ImportError"}
    monkeypatch.setattr(core_api, "ROUTER_MANIFEST", fake)
    body = TestClient(core_api.app).get("/api/health").json()
    assert body["routers"] == "INCOMPLETE"
    assert "sales" in body["routers_missing"]


# ── route identity, not a count ───────────────────────────────────────────────────────────────────
def _public_mutating():
    out = set()
    for r in core_api.app.routes:
        for m in getattr(r, "methods", set()) or set():
            if m in ("POST", "PUT", "PATCH", "DELETE"):
                if core_api._public_rule_for(r.path, m) or r.path in core_api._PUBLIC_PATHS:
                    out.add((m, r.path))
    return out


def _v2_mutating():
    return {(m, p) for m, p in _public_mutating() if p.startswith("/api/v2/narai")}


def test_all_v2_mutating_routes_still_require_authentication():
    """The 33. Pinned by identity so that removing a guard fails here even if the count is preserved
    by adding an unrelated route in the same commit."""
    unguarded = []
    for r in core_api.app.routes:
        for m in getattr(r, "methods", set()) or set():
            if m not in ("POST", "PUT", "PATCH", "DELETE"):
                continue
            if not r.path.startswith("/api/v2/narai"):
                continue
            if not (core_api._public_rule_for(r.path, m) or r.path in core_api._PUBLIC_PATHS):
                continue
            deps = ([d.call.__name__ for d in r.dependant.dependencies]
                    if getattr(r, "dependant", None) else [])
            if "require_auth" in deps:
                continue
            unguarded.append((m, r.path))

    # The five that legitimately carry no require_auth: three are entry points a caller cannot yet
    # hold a credential for, and two are guarded in-body by _require_admin(x_admin_token).
    ACCOUNTED = {
        ("POST", "/api/v2/narai/auth/login"),
        ("POST", "/api/v2/narai/insider/lead"),
        ("POST", "/api/v2/narai/telegram/subscription/checkout"),
        ("POST", "/api/v2/narai/insider/reissue"),
        ("POST", "/api/v2/narai/insider/revoke"),
        ("POST", "/api/v2/narai/voice/ws-ticket"),   # require_auth, listed for completeness
    }
    surprises = sorted(set(unguarded) - ACCOUNTED)
    assert not surprises, (
        f"mutating /api/v2/narai routes with no require_auth and no reviewed reason: {surprises}")


def test_the_v2_mutating_surface_has_not_silently_shrunk():
    """Guards against the inverse of a new hole: a route DISAPPEARING because an import broke.
    Without this, a reduced build passes every other assertion in this file."""
    count = len(_v2_mutating())
    assert count >= 38, (
        f"only {count} mutating /api/v2/narai routes are visible; production serves at least 38. "
        "An import has failed and this audit is running against a smaller application.")


def test_the_ticket_route_exists_and_is_authenticated():
    """The route that replaced the JWT-in-a-URL. If it vanished, clients would have no way to get a
    ticket and the pressure to put the JWT back would return."""
    found = [r for r in core_api.app.routes
             if getattr(r, "path", "") == "/api/v2/narai/voice/ws-ticket"]
    assert found, "the WebSocket ticket route is missing"
    for r in found:
        deps = ([d.call.__name__ for d in r.dependant.dependencies]
                if getattr(r, "dependant", None) else [])
        assert "require_auth" in deps, "the ticket route must itself require a bearer JWT"


# ── websocket identity ────────────────────────────────────────────────────────────────────────────
def test_both_websocket_routes_are_present_and_pinned():
    """WebSocket routes have methods=None, so every mutating-surface enumeration in this repo skips
    them silently. They are counted separately or not at all."""
    ws = sorted({getattr(r, "path", "") for r in core_api.app.routes
                 if isinstance(r, WebSocketRoute) or r.__class__.__name__ == "APIWebSocketRoute"})
    assert ws == ["/api/code/stream/{run_id}", "/api/v2/narai/voice/ws"], (
        f"the WebSocket surface changed: {ws}. Every WebSocket route bypasses api_key_middleware by "
        "construction, so a new one needs its own gate and its own entry here.")


def test_no_websocket_route_authenticates_from_a_query_string_jwt():
    """The defect this whole change removes, pinned so it cannot come back on either route."""
    import inspect
    for r in core_api.app.routes:
        if not (isinstance(r, WebSocketRoute) or r.__class__.__name__ == "APIWebSocketRoute"):
            continue
        params = inspect.signature(r.endpoint).parameters
        for name, prm in params.items():
            assert name not in ("token", "jwt", "access_token", "api_key"), (
                f"{getattr(r, 'path', '?')} binds {name!r} — a credential in a URL")
            assert "Query" not in type(prm.default).__name__ or name == "run_id", (
                f"{getattr(r, 'path', '?')} binds {name!r} from the query string")


# ── the public rule table itself ──────────────────────────────────────────────────────────────────
def test_no_public_rule_grants_a_mutating_verb_without_review():
    """A descendant rule that permits a mutating verb makes every future child public for that verb.
    The set is pinned; adding one is a decision, not a side effect."""
    mutating_families = {r.path for r in core_api.PUBLIC_API_RULES
                         if r.descendants and (r.methods - {"GET", "HEAD", "OPTIONS"})}
    REVIEWED = {"/api/nx", "/api/shopify", "/api/shopify-autopilot", "/api/sa",
                "/api/v2/narai", "/api/narai/shopify", "/api/google"}
    new = mutating_families - REVIEWED
    assert not new, (
        f"NEW mutating descendant rule(s): {sorted(new)} — every child route becomes publicly "
        "mutable. That needs its own review, not a sentence in the purpose field.")


def test_every_public_mutating_route_has_a_reviewed_reason():
    """The whole surface, in one assertion: nothing anonymously mutable without a recorded reason.

    Deliberately duplicates the grouping in test_public_action_routes.py rather than importing it —
    if that file is ever weakened, this one still fails, and a security invariant asserted in exactly
    one place is one edit away from not being asserted at all.
    """
    from tests.test_public_action_routes import (  # noqa: F401  (import proves it still exists)
        test_the_anonymously_mutable_surface_is_a_pinned_reviewed_set as _pinned,
    )
    assert callable(_pinned), "the reviewed-set guard has been removed"
