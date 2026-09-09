"""No route that starts, stops, resets or publishes may be anonymously public.

THE DEFECT, AND IT WAS PARTLY INTRODUCED BY THE FIX BEFORE IT. PR #73 replaced `startswith()` prefix
matching with an explicit `PublicRule` table — but it carried three entries forward as
`descendants=True` on the strength of their old comments:

    PublicRule("/api/narai-autopilot", {GET,POST,OPTIONS}, True, "...surface with its own auth.")
    PublicRule("/api/factory",         {GET,POST,OPTIONS}, True, "...callbacks with their own token check.")
    PublicRule("/api/qc",              {GET,POST,OPTIONS}, True, "...callbacks with their own token check.")

Those comments are false. The handlers perform no authentication of any kind. Writing the purpose
down was supposed to force that judgement; it recorded a claim instead of checking one.

Eight action routes were therefore anonymously reachable on production:

    POST   /api/factory/start                          POST   /api/narai-autopilot/start
    POST   /api/factory/stop                           POST   /api/narai-autopilot/stop
    DELETE /api/factory/reset                          POST   /api/narai-autopilot/reels
    POST   /api/qc/review                              POST   /api/narai-autopilot/queue/{idx}/mark_done

`POST /api/narai-autopilot/start` is the severe one. It spawns a daemon thread that publishes to the
company's live Facebook, Instagram, Twitter/X, Telegram and WordPress accounts, creates and
**publishes priced Gumroad products**, creates Etsy listings, publishes Shopify products, and spends
against the Anthropic budget. It takes no body and no parameters, so a single unauthenticated POST
from any origin starts it. There is no CSRF protection anywhere in the app, and a bodyless POST is a
CORS "simple request" — no preflight — so any web page can fire it cross-origin.

Confirmed on production without invoking anything, using a method the route does not accept
(405 = routing reached, i.e. exempt; 401 = gated):

    GET /api/narai-autopilot/start  -> 405        GET /api/factory/reset -> 405
    GET /api/narai-autopilot/stop   -> 405

TWO INDEPENDENT EXEMPTIONS, again. Each of these is ALSO an exact member of `_PUBLIC_PATHS`, which is
checked separately and is METHOD-BLIND. Fixing only the rule table would leave the hole open, and
fixing only `_PUBLIC_PATHS` would too.

THE FIX. The three descendant rules become GET-only, so every read a dashboard polls stays public
while every POST/DELETE under them is gated — and the action entries are removed from
`_PUBLIC_PATHS`. Nothing here invokes an action handler: spies record and refuse.
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

# Every route under the three families that DOES something.
ACTIONS = [
    ("POST", "/api/factory/start"),
    ("POST", "/api/factory/stop"),
    ("DELETE", "/api/factory/reset"),
    ("POST", "/api/qc/review"),
    ("POST", "/api/narai-autopilot/start"),
    ("POST", "/api/narai-autopilot/stop"),
    ("POST", "/api/narai-autopilot/reels"),
    ("POST", "/api/narai-autopilot/queue/0/mark_done"),
    # Found by enumerating the whole public mutating surface AFTER the three families were fixed.
    # Same shape, same severity class: anonymous start/stop of a money-spending automation.
    # POST /api/pod/start runs run_pod_session() -> DALL-E 3 image generation (paid), Printify
    # product creation, and publication to the live Shopify store.
    ("POST", "/api/pod/start"),
    ("POST", "/api/pod/stop"),
    ("POST", "/api/nexora/recruit"),
    ("POST", "/api/nexora/growth"),
]

# Reads the dashboards poll. These must KEEP working anonymously — the fix must not be a blunt
# family-wide gate that breaks the operator surface.
READS = [
    "/api/factory/status", "/api/factory/log", "/api/factory/alltime",
    "/api/narai-autopilot/status", "/api/narai-autopilot/log", "/api/narai-autopilot/queue",
    "/api/qc/results", "/api/qc/stats",
    "/api/pod/memory", "/api/pod/log",
]

UNAUTHORIZED = {
    "anonymous": ({}, {}),
    "bad-key": ({"X-API-Key": "nope"}, {}),
    "operator-session": ({}, {COOKIE_NAME: osess.mint_session("operator", secret=SESSION_SECRET,
                                                              ttl_seconds=3600)}),
    "viewer-session": ({}, {COOKIE_NAME: osess.mint_session("viewer", secret=SESSION_SECRET,
                                                            ttl_seconds=3600)}),
    "signed-out": ({}, {COOKIE_NAME: ""}),
    "foreign-secret": ({}, {COOKIE_NAME: osess.mint_session("owner", secret="other",
                                                            ttl_seconds=3600)}),
    "forged-verifier": ({"x-kai-verifier-token": "Zm9yZ2Vk.Zm9yZ2Vk"}, {}),
}


@pytest.fixture
def client():
    return TestClient(core_api.app)


@pytest.fixture(autouse=True)
def _prod(monkeypatch):
    monkeypatch.setattr(core_api, "_APP_ENV", "production", raising=False)


# ── 1. no unauthorized identity may act ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("method,path", ACTIONS)
@pytest.mark.parametrize("label", sorted(UNAUTHORIZED))
def test_no_unauthorized_identity_reaches_an_action(client, method, path, label):
    headers, cookies = UNAUTHORIZED[label]
    r = client.request(method, path, headers=headers, cookies=cookies, json={})
    assert r.status_code == 401, f"{label} reached {method} {path} ({r.status_code})"


@pytest.mark.parametrize("method,path", ACTIONS)
def test_the_release_verifier_cannot_act(client, method, path):
    from app.services.holding.verifier_role import mint_verifier_token, VERIFIER_HEADER
    tok = mint_verifier_token(subject="action-audit",
                              secret=os.environ["RELEASE_VERIFIER_SIGNING_SECRET"])
    r = client.request(method, path, headers={VERIFIER_HEADER: tok}, json={})
    assert r.status_code in (401, 403)


# ── 2. THE AUTOPILOT MUST NEVER START ─────────────────────────────────────────────────────────────
def test_no_unauthorized_request_starts_or_stops_the_autopilot(client, monkeypatch):
    """The severe one. A record-and-refuse spy replaces the autopilot module entirely, so even a
    successful bypass cannot publish to a live social account or create a priced product."""
    import sys, types
    fired = []

    fake = types.ModuleType("core.narai_autopilot")
    def _spy(name):
        def _f(*a, **k):
            fired.append(name)
            raise RuntimeError(f"SPY REFUSED: {name} must not be reachable")
        return _f
    for fn in ("start_autopilot_background", "stop_autopilot", "get_ap_status",
               "run_autopilot_session", "generate_reels"):
        setattr(fake, fn, _spy(fn))
    monkeypatch.setitem(sys.modules, "core.narai_autopilot", fake)

    for label, (headers, cookies) in UNAUTHORIZED.items():
        for method, path in ACTIONS:
            if "narai-autopilot" not in path:
                continue
            client.request(method, path, headers=headers, cookies=cookies, json={})
    assert fired == [], f"an unauthorized request reached the autopilot: {fired}"


def test_no_unauthorized_request_starts_the_pod_engine(client, monkeypatch):
    """run_pod_session generates paid DALL-E images, creates Printify products and publishes them
    to the live Shopify store. Spy the engine so a bypass cannot spend or publish."""
    import sys, types
    fired = []
    fake = types.ModuleType("core.narai_pod_engine")
    for fn in ("run_pod_session", "get_pod_session_status", "get_pod_memory_stats"):
        setattr(fake, fn, lambda *a, _n=fn, **k: fired.append(_n))
    fake._session_state = {}
    monkeypatch.setitem(sys.modules, "core.narai_pod_engine", fake)
    for headers, cookies in UNAUTHORIZED.values():
        for method, path in ACTIONS:
            if "/api/pod/" in path:
                client.request(method, path, headers=headers, cookies=cookies, json={})
    assert fired == [], f"an unauthorized request reached the POD engine: {fired}"


def test_no_unauthorized_request_resets_the_factory(client, monkeypatch):
    """/api/factory/reset clears today's products and truncates the log file. Spy the persistence
    layer so a bypass cannot destroy state."""
    fired = []
    for fn in ("_pf_save_state", "_pf_load_state"):
        if hasattr(core_api, fn):
            monkeypatch.setattr(core_api, fn,
                                lambda *a, _n=fn, **k: fired.append(_n), raising=False)
    for label, (headers, cookies) in UNAUTHORIZED.items():
        client.request("DELETE", "/api/factory/reset", headers=headers, cookies=cookies)
    assert fired == [], f"an unauthorized request reached factory state: {fired}"


def test_no_outbound_call_or_subprocess_from_a_refused_action(client, monkeypatch):
    import subprocess, urllib.request, threading
    fired = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fired.append("Popen"), raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fired.append("run"), raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fired.append("urlopen"),
                        raising=False)
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: fired.append("Thread") or (_ for _ in ()).throw(
                            AssertionError("a thread was spawned by a refused request")),
                        raising=False)
    for method, path in ACTIONS:
        client.request(method, path, json={})
    assert fired == [], f"a refused action still caused: {fired}"


# ── 3. reads must keep working ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", READS)
def test_dashboard_reads_stay_public(client, path):
    """The fix must be surgical. Gating the whole family would break the operator dashboards, which
    poll these anonymously today."""
    r = client.get(path)
    assert r.status_code != 401, f"{path} was gated — the read surface regressed"


# ── 4. both exemption mechanisms, and the matcher ─────────────────────────────────────────────────
@pytest.mark.parametrize("method,path", ACTIONS)
def test_no_public_rule_matches_an_action(method, path):
    assert core_api._public_rule_for(path, method) is None, \
        f"a PublicRule still matches {method} {path}"


@pytest.mark.parametrize("path", READS)
def test_each_read_is_still_anonymously_reachable(path):
    """Either mechanism is fine here — the property is reachability, not which table grants it."""
    assert core_api._public_rule_for(path, "GET") or path in core_api._PUBLIC_PATHS, \
        f"{path} is no longer anonymously reachable — the operator dashboards would break"


def test_action_paths_are_not_in_the_method_blind_public_set():
    """_PUBLIC_PATHS is exact-match but METHOD-BLIND, so an action listed there is public for every
    verb regardless of the rule table. This is the second, independent exemption."""
    for _m, p in ACTIONS:
        base = p.split("/{")[0]
        assert base not in core_api._PUBLIC_PATHS, \
            f"{base} is still in _PUBLIC_PATHS — the method-blind exemption is still open"


def test_the_three_families_are_get_only():
    """The families keep descendant rules so reads work, but only for GET. A future POST added under
    them is gated by default rather than public by default."""
    for family in ("/api/narai-autopilot", "/api/factory", "/api/qc",
                   "/api/shopify", "/api/sa", "/api/shopify-autopilot"):
        rule = next((r for r in core_api.PUBLIC_API_RULES if r.path == family), None)
        assert rule is not None, f"{family} lost its read rule — dashboards would break"
        assert rule.methods == frozenset({"GET"}), \
            f"{family} permits {sorted(rule.methods)}; an action family must be GET-only"


def test_mutating_descendant_rules_are_a_pinned_reviewed_set():
    """A descendant rule permitting a mutating verb makes EVERY future child public for that verb.

    An earlier version of this test looked for the word "own" or "webhook" in the purpose string.
    That is exactly the wrong shape, and this incident is the proof: /api/narai-autopilot's purpose
    said "with its own auth" and the handlers had none, so a keyword test would have passed the
    false claim it was supposed to catch. A sentence is not evidence.

    So the set is PINNED instead. Adding a mutating descendant rule fails here and has to be a
    deliberate act with its own review, and the claims below are recorded as UNVERIFIED — each
    asserts a protection mechanism inside its routers that nobody has yet confirmed the way
    /api/narai-autopilot's claim was confirmed false.
    """
    MUTATING_DESCENDANTS_UNVERIFIED = {
        "/api/nx",                 # claims: own Bearer token auth in the routers
        "/api/v2/narai",           # claims: own JWT auth on every route
        "/api/narai/shopify",      # claims: own Bearer auth
        "/api/google",             # claims: state-based CSRF, must be reachable pre-session
    }
    actual = {r.path for r in core_api.PUBLIC_API_RULES
              if r.descendants and (r.methods - {"GET", "HEAD", "OPTIONS"})}
    new = actual - MUTATING_DESCENDANTS_UNVERIFIED
    assert not new, (
        f"NEW mutating descendant rule(s): {sorted(new)} — every child route becomes publicly "
        "mutable. This needs its own review, not a sentence in the purpose field.")
    gone = MUTATING_DESCENDANTS_UNVERIFIED - actual
    assert not gone, (
        f"{sorted(gone)} no longer permits mutating verbs — if that was a deliberate hardening, "
        "shrink this set in the same commit so the record stays accurate.")


def test_the_audited_families_are_no_longer_mutating():
    """The six this patch verified are out of the unverified set, by being GET-only.

    /api/nx and /api/v2/narai stay in it: their claims survived scrutiny (in-body `_nx_require_*`
    and `require_auth` respectively), but only some of their routes were sampled, so "verified" is
    too strong a word for the family as a whole.
    """
    for family in ("/api/narai-autopilot", "/api/factory", "/api/qc",
                   "/api/shopify", "/api/sa", "/api/shopify-autopilot"):
        rule = next(r for r in core_api.PUBLIC_API_RULES if r.path == family)
        assert rule.methods == frozenset({"GET"})


# ── 5. THE DURABLE GUARD ──────────────────────────────────────────────────────────────────────────
def test_no_unauthenticated_mutating_route_is_anonymously_public():
    """Enumerate the surface instead of listing routes by hand.

    The public set is assembled by FOURTEEN scattered sites: the `_PUBLIC_PATHS` literal, eleven
    `_PUBLIC_PATHS.add(...)` calls, and three `for _p in [...]` loops that run at import time
    thousands of lines from the declaration — one of them 3,000 lines away, right above the handlers
    it exempts. Nobody can read the effective public surface from any single place, which is why
    three separate incidents each found "the" anonymous route and each missed the rest.

    So this test does not name routes. It walks every registered route, asks the real matchers
    whether it is anonymously reachable, and reads the handler's own source for any authentication
    signal. A new exemption added at ANY of the fourteen sites fails here.

    Both directions of scan were needed. A dependency-only scan called /api/nx a false claim —
    13 mutating routes, zero `Depends`. Reading the source showed `_nx_require_creator(request)` in
    the body: the auth is real, just not declarative. Trusting the route signature would have been
    the same mistake as trusting the purpose comment, in the opposite direction.
    """
    import inspect, re
    AUTH = re.compile(r"_require_|require_auth|verify_admin|verify_api_key|current_user|"
                      r"_nx_require|check_token|_verify_|signature|hmac", re.I)
    # Deliberately public entry points: unauthenticated by design because the caller cannot yet
    # have a credential (login, signup, lead capture, public chat) or authenticates by another
    # scheme (webhook signatures). Each is a customer-facing surface, not an operator action.
    ENTRY_POINTS = {
        "/api/auth/login", "/api/lead", "/api/subscribe", "/api/public/chat",
        "/api/narai/chat", "/api/narai/conversations", "/api/narai/shopify/billing/checkout",
        "/api/v2/narai/auth/login", "/api/v2/narai/insider/lead",
        "/api/v2/narai/telegram/subscription/checkout", "/api/payhip/mark-registered",
    }
    offenders = set()
    for r in core_api.app.routes:
        for m in getattr(r, "methods", set()) or set():
            if m not in ("POST", "PUT", "PATCH", "DELETE"):
                continue
            path = r.path
            if not (core_api._public_rule_for(path, m) or path in core_api._PUBLIC_PATHS):
                continue
            if "webhook" in path or path in ENTRY_POINTS or path.startswith("/api/nx/"):
                continue
            deps = [d.call.__name__ for d in r.dependant.dependencies] if getattr(r, "dependant", None) else []
            try:
                src = inspect.getsource(r.endpoint)
            except Exception:
                src = ""
            if deps or AUTH.search(src):
                continue
            offenders.add((m, path))
    assert not offenders, (
        "anonymously reachable, mutating, and with no authentication signal anywhere in the "
        f"handler:\n" + "\n".join(f"  {m} {p}" for m, p in sorted(offenders)))


def test_the_public_surface_is_pinned():
    """A count is a cheap tripwire for an exemption added where the scan above has a blind spot."""
    assert len(core_api.PUBLIC_API_RULES) == 12
    assert len(core_api._PUBLIC_PATHS) == 96, (
        f"the public path set is now {len(core_api._PUBLIC_PATHS)}; if you added one deliberately, "
        "update this number in the same commit so the change is visible in review")
