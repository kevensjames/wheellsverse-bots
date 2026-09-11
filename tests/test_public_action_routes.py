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



def _importable(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def test_the_environment_can_see_the_whole_surface():
    """This suite is only as good as the routes that actually loaded.

    core/api.py mounts the NarAI v2 routers inside try/except blocks, so a missing optional
    dependency does not raise — it logs a warning and those routes silently never exist. Every
    earlier audit in this sequence ran in a venv without chromadb, litellm, cachetools or aiosqlite,
    and therefore walked a route table ~120 routes smaller than production's, with 33 mutating routes
    among the ones it could not see.

    A security guard that quietly audits less than production is worse than no guard, because it
    reports success while doing so. This fails loudly instead.
    """
    missing = [m for m in ("chromadb", "litellm", "cachetools", "aiosqlite") if not _importable(m)]
    assert not missing, (
        f"optional deps missing: {missing} — the /api/v2/narai routers will not load and this suite "
        "audits a SMALLER surface than production serves. All four are pinned in requirements.txt; "
        "install them before trusting a green run here.")


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
def test_the_anonymously_mutable_surface_is_a_pinned_reviewed_set():
    """Enumerate the surface and pin it. Do not try to detect authentication.

    The previous version of this test scanned each handler's source for an auth signal, and that
    approach failed in both directions within one session:

      FALSE NEGATIVE  POST /api/shopify/register-webhooks passed the scan because the word
                      "webhook" was in its path, so the test declared it protected. It had no
                      authentication at all and would re-register every Shopify webhook — that is,
                      repoint the store's webhook delivery — for any anonymous caller. It survived
                      the commit that was supposed to close exactly this class.
      FALSE POSITIVE  /api/v2/narai/insider/revoke and /reissue were reported as unguarded because
                      the scan looked for a fixed list of guard names and theirs, _require_admin,
                      was not on it. Both are properly protected.

    Detecting "is this authenticated?" from source needs a name list or a regex, and both are
    guesses about vocabulary. So this test stops guessing. It answers only the question it can
    answer exactly — "can an anonymous request reach this route?" — using the real matchers, and
    compares the result to a set reviewed by a human. Adding an anonymously-reachable mutating
    route now fails until someone puts it here deliberately, whatever it is called.

    A new entry belongs in exactly one of these three groups, and the group is the review.
    """
    # Unauthenticated by design: the caller cannot yet hold a credential.
    ENTRY_POINTS = {
        ("POST", "/api/auth/login"), ("POST", "/api/lead"), ("POST", "/api/subscribe"),
        ("POST", "/api/public/chat"), ("POST", "/api/narai/chat"),
        ("POST", "/api/narai/conversations"),
        ("POST", "/api/narai/shopify/billing/checkout"),
        ("POST", "/api/v2/narai/auth/login"), ("POST", "/api/v2/narai/insider/lead"),
        ("POST", "/api/v2/narai/telegram/subscription/checkout"),
        ("POST", "/api/payhip/mark-registered"),
        ("POST", "/api/nx/login"), ("POST", "/api/nx/logout"), ("POST", "/api/nx/register"),
        ("POST", "/api/nx/fan/login"), ("POST", "/api/nx/fan/logout"),
        ("POST", "/api/nx/fan/register"), ("POST", "/api/nx/subscribe"),
    }
    # Authenticated by a scheme other than ours. Stripe and Shopify verify a signature; the other
    # four DO NOT and are carried as a known open finding, not as something this test endorses.
    WEBHOOKS = {
        ("POST", "/api/stripe/webhook"), ("POST", "/api/shopify/webhook"),
        ("POST", "/api/nx/stripe-webhook"),
        ("POST", "/api/telegram/webhook"), ("POST", "/api/whatsapp/webhook"),
        ("POST", "/api/beehiiv/webhook"), ("POST", "/api/payhip/webhook"),
    }
    # NarAI v2. THESE WERE INVISIBLE TO EVERY EARLIER AUDIT IN THIS SEQUENCE. The /api/v2/narai
    # routers are mounted inside try/except blocks in core/api.py, so a missing optional dependency
    # does not raise — it logs a warning and the routes silently never exist. The local venv lacked
    # chromadb, litellm, cachetools and aiosqlite, so roughly 120 production routes were absent from
    # the table this test walks, 33 of them mutating. Production installs the full requirements and
    # serves every one.
    #
    # Now that they load, the PublicRule purpose "NarAI v2 uses its own JWT auth on every route" is
    # VERIFIED rather than assumed: every route below carries a require_auth dependency. It had been
    # recorded as an UNVERIFIED claim precisely because nothing here could see it.
    V2_NARAI_REQUIRE_AUTH = {
        ("DELETE", "/api/v2/narai/memory/{key}"),
        ("DELETE", "/api/v2/narai/ops/tasks/{task_id}"),
        ("PATCH", "/api/v2/narai/sales/deals/amount"),
        ("PATCH", "/api/v2/narai/sales/deals/stage"),
        ("POST", "/api/v2/narai/briefing/markdown"),
        ("POST", "/api/v2/narai/briefing/now"),
        ("POST", "/api/v2/narai/briefing/preview"),
        ("POST", "/api/v2/narai/briefing/test"),
        ("POST", "/api/v2/narai/chat"),
        ("POST", "/api/v2/narai/chat/stream"),
        ("POST", "/api/v2/narai/content/batch"),
        ("POST", "/api/v2/narai/content/generate"),
        ("POST", "/api/v2/narai/creative/images"),
        ("POST", "/api/v2/narai/creative/music"),
        ("POST", "/api/v2/narai/creative/video"),
        ("POST", "/api/v2/narai/kdp/metadata"),
        # Added with the WebSocket ticket flow: it is the authenticated HTTPS POST that
        # replaced the JWT-in-a-URL on /api/v2/narai/voice/ws. Carries require_auth.
        ("POST", "/api/v2/narai/voice/ws-ticket"),
        ("POST", "/api/v2/narai/kdp/royalties"),
        ("POST", "/api/v2/narai/memory"),
        ("POST", "/api/v2/narai/memory/recall"),
        ("POST", "/api/v2/narai/ops/habits"),
        ("POST", "/api/v2/narai/ops/habits/{habit_id}/checkin"),
        ("POST", "/api/v2/narai/ops/tasks"),
        ("POST", "/api/v2/narai/ops/tasks/{task_id}/complete"),
        ("POST", "/api/v2/narai/rag/ingest/file"),
        ("POST", "/api/v2/narai/rag/ingest/text"),
        ("POST", "/api/v2/narai/rag/query"),
        ("POST", "/api/v2/narai/research"),
        ("POST", "/api/v2/narai/sales/deals"),
        ("POST", "/api/v2/narai/sales/outreach"),
        ("POST", "/api/v2/narai/sales/score"),
        ("POST", "/api/v2/narai/sales/score_batch"),
        ("POST", "/api/v2/narai/skills/activate/{name}"),
        ("POST", "/api/v2/narai/skills/deactivate"),
    }

    # Guarded inside the handler rather than by a dependency — each one read and confirmed.
    IN_HANDLER_AUTH = {
        ("PATCH", "/api/nx/me"), ("POST", "/api/nx/messages"), ("POST", "/api/nx/payouts"),
        ("POST", "/api/nx/posts"), ("DELETE", "/api/nx/posts/{post_id}"),
        ("POST", "/api/narai/shopify/test-printify"),
        ("POST", "/api/narai/shopify/merchants/{merchant_id}/test-product"),
        ("POST", "/api/v2/narai/briefing/now"), ("POST", "/api/v2/narai/briefing/preview"),
        ("POST", "/api/v2/narai/briefing/test"), ("POST", "/api/v2/narai/briefing/markdown"),
        ("POST", "/api/v2/narai/insider/revoke"), ("POST", "/api/v2/narai/insider/reissue"),
    }
    REVIEWED = ENTRY_POINTS | WEBHOOKS | IN_HANDLER_AUTH | V2_NARAI_REQUIRE_AUTH

    # WHAT THIS ENUMERATION CANNOT SEE. A WebSocket route has methods=None, so the inner loop below
    # never runs for one and it is skipped in silence — this found 387 mutating routes and missed
    # /api/code/stream/{run_id}, which was reachable with no credential at all because
    # api_key_middleware is @app.middleware("http") and never sees a WebSocket scope. WebSocket
    # routes are pinned separately in tests/test_websocket_auth_boundary.py. A guard pins only the
    # part of the surface it knows how to enumerate, and saying so is part of the guard.
    actual = set()
    for r in core_api.app.routes:
        for m in getattr(r, "methods", set()) or set():
            if m not in ("POST", "PUT", "PATCH", "DELETE"):
                continue
            if core_api._public_rule_for(r.path, m) or r.path in core_api._PUBLIC_PATHS:
                actual.add((m, r.path))

    unreviewed = actual - REVIEWED
    assert not unreviewed, (
        "anonymously reachable and mutating, and not in any reviewed group:\n"
        + "\n".join(f"  {m} {p}" for m, p in sorted(unreviewed))
        + "\n\nGate it, or add it to a group above with a reason.")

    departed = REVIEWED - actual
    if departed:
        # A reduced-dependency environment makes routes VANISH rather than appear, which would let
        # this test pass while auditing a smaller surface than production serves. That is exactly the
        # failure mode that hid 33 mutating /api/v2/narai routes from every earlier audit in this
        # sequence, so it is named rather than tolerated.
        missing_optional = [m for m in ("chromadb", "litellm", "cachetools", "aiosqlite")
                            if not _importable(m)]
        assert not missing_optional, (
            f"{len(departed)} reviewed routes are absent because optional dependencies are missing: "
            f"{missing_optional}. This environment audits a SMALLER surface than production serves — "
            f"a green run here would be meaningless. All are pinned in requirements.txt. "
            f"Absent here, for example: {sorted(pp for _m, pp in departed)[:3]}")
        assert False, (
            "these are no longer anonymously reachable — good, but remove them here in the same "
            "commit so the reviewed set keeps describing reality:\n"
            + "\n".join(f"  {m} {pp}" for m, pp in sorted(departed)))


def test_register_webhooks_is_gated():
    """The route the name-based scan waved through. It re-registers every Shopify webhook, which
    repoints where the store delivers its events, and it had no authentication of any kind."""
    assert core_api._public_rule_for("/api/shopify/register-webhooks", "POST") is None
    assert "/api/shopify/register-webhooks" not in core_api._PUBLIC_PATHS


def test_the_public_surface_is_pinned():
    """A count is a cheap tripwire for an exemption added where the scan above has a blind spot."""
    assert len(core_api.PUBLIC_API_RULES) == 12
    assert len(core_api._PUBLIC_PATHS) == 94, (
        f"the public path set is now {len(core_api._PUBLIC_PATHS)}; if you added one deliberately, "
        "update this number in the same commit so the change is visible in review")


def test_a_get_that_computes_is_not_public():
    """Found by probing the running app: GET /api/sa/trend-scan returned 500 from deep inside the
    Anthropic client. Its docstring calls it a "cached read"; on a cold cache the read performs the
    scrape and the LLM classification. A GET-only rule is only as safe as the GETs behind it."""
    for path in core_api._NEVER_PUBLIC:
        assert core_api._public_rule_for(path, "GET") is None, f"{path} matched a rule"
        assert path not in core_api._PUBLIC_PATHS, f"{path} is still an exact public entry"
    assert "/api/sa/trend-scan" in core_api._NEVER_PUBLIC
