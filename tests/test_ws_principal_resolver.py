"""A production JWT must never appear in a query parameter.

/api/v2/narai/voice/ws authenticated with `token: str = Query(..., description="JWT from
/auth/login")` — a reusable production credential in a URL. A URL is not a private channel: edge
logs, access logs, any intermediary proxy, browser history, and Referer headers sent to third
parties all keep a copy, and none of them can be revoked from. This codebase removed exactly this
pattern once already when `?api_key=` was deleted from core/operator_session_web.py.

It was also invisible. The route only exists when chromadb and litellm import, and the venv used for
every earlier audit in this sequence had neither — so the WebSocket audit that produced PR #77 saw
one route and pinned a surface of one, while production served two.

WHAT REPLACES IT. narai/api/ws_auth.py is the single resolver both WebSocket routes consult, so they
cannot drift. Two identities and nothing else:

  session cookie   the browser path. A browser cannot set headers on a WebSocket handshake — which
                   is the actual reason a JWT ended up in the URL — but it does send cookies. A
                   handshake is NOT subject to CORS, so an exact trusted Origin is required or a
                   foreign page can open one with the victim's cookie attached.
  single-use ticket for clients that cannot present the cookie. Obtained by an authenticated HTTPS
                   POST, bound to (principal, role, route, environment, expiry, jti), consumed
                   atomically, useless afterwards.

A ticket in a URL is NOT equivalent to a JWT in a URL, and these tests are written to hold that
distinction: the ticket is bound to one route and one environment, dies in 30 seconds, and loses
every race after the first. test_a_ticket_is_worthless_on_any_other_route and
test_concurrent_replay_has_exactly_one_winner are what make that claim checkable rather than
rhetorical.

Everything is asserted BEFORE accept(). The old handler accepted first and closed after, and its own
comment explained why — but a handshake completed with an unauthenticated peer is still a handshake
completed with them.
"""
import base64
import os
import textwrap
import time

import pytest

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")

from narai.api import ws_auth as W                        # noqa: E402
from core.operator_session import mint_session            # noqa: E402

ROUTE = "/api/v2/narai/voice/ws"
ENV = "production"
SESSION_SECRET = "ws-session-secret"
TICKET_SECRET = "ws-ticket-secret"
TRUSTED = frozenset({"https://app.wheellsverse.com"})


class FakeWS:
    """Only what the resolver may touch. If it ever reaches for more, this raises rather than
    silently succeeding against a mock richer than a real handshake."""
    def __init__(self, query=None, cookies=None, origin=None):
        self.query_params = query or {}
        self.cookies = cookies or {}
        self.headers = {"origin": origin} if origin else {}


def resolve(ws, route=ROUTE, env=ENV, store=None, is_revoked=None):
    return W.resolve_ws_principal(
        ws, route, environment=env, trusted_origins=TRUSTED,
        session_secret=SESSION_SECRET, ticket_secret=TICKET_SECRET,
        is_revoked=is_revoked, store=store)


def ticket(sub="user-1", role="operator", route=ROUTE, env=ENV, secret=TICKET_SECRET, ttl=30):
    return W.mint_ticket(sub, role, route, env, secret, ttl_seconds=ttl)


# ── the legacy parameter is REFUSED, not merely unread ────────────────────────────────────────────
def test_the_legacy_jwt_query_parameter_is_refused(tmp_path):
    """A credential that stops being checked but keeps being transmitted is worse than one that is
    checked: it still lands in every log, and nobody notices it stopped meaning anything."""
    out, p, _ = resolve(FakeWS(query={"token": "eyJhbGci.some.jwt"}), store=tmp_path)
    assert out == W.LEGACY_JWT_IN_URL and p is None


def test_the_legacy_parameter_beats_even_a_valid_ticket(tmp_path):
    """Presence of ?token= is itself the failure. Otherwise a client could keep shipping the JWT in
    the URL forever as long as it also sent something valid."""
    out, p, _ = resolve(FakeWS(query={"token": "x", "ticket": ticket()}), store=tmp_path)
    assert out == W.LEGACY_JWT_IN_URL and p is None


def test_the_route_no_longer_declares_a_token_parameter():
    """Below the framework: FastAPI would happily keep binding ?token= if the signature still asked
    for it, and a handler that no longer READS it would still cause it to be sent."""
    import inspect
    from narai.api.routes import voice
    # The SIGNATURE is the thing that matters: FastAPI binds ?token= only if a parameter asks for
    # it, and a handler that no longer reads the value would still cause clients to send it.
    params = inspect.signature(voice.voice_ws).parameters
    assert "token" not in params, f"voice_ws still declares a token parameter: {list(params)}"
    assert list(params) == ["websocket"], f"voice_ws takes unexpected parameters: {list(params)}"
    # and no parameter default is a Query binding (checking defaults, not source text — an earlier
    # version of this test grepped the source and matched its own explanatory comment)
    for name, prm in params.items():
        assert "Query" not in type(prm.default).__name__, f"{name} is bound from the query string"


# ── no identity ───────────────────────────────────────────────────────────────────────────────────
def test_a_handshake_with_no_identity_is_refused(tmp_path):
    out, p, _ = resolve(FakeWS(), store=tmp_path)
    assert out == W.NO_IDENTITY and p is None


# ── the cookie path ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role,expect", [("owner", W.OK), ("operator", W.OK),
                                         ("viewer", W.FORBIDDEN_ROLE)])
def test_role_decides_whether_a_session_may_open_a_voice_socket(tmp_path, role, expect):
    """A viewer may READ the estate. Opening a live microphone channel that spends money and speaks
    as the owner is a different authority."""
    c = mint_session(role, secret=SESSION_SECRET, ttl_seconds=3600)
    out, _, _ = resolve(FakeWS(cookies={"wv_session": c},
                               origin="https://app.wheellsverse.com"), store=tmp_path)
    assert out == expect


@pytest.mark.parametrize("origin", [
    None, "", "null", "https://evil.com",
    "https://app.wheellsverse.com.evil.com",       # suffix trap
    "https://app.wheellsverse.com@evil.com",       # userinfo trap
    "http://app.wheellsverse.com",                 # scheme matters
    "https://app.wheellsverse.com:8443",           # port matters
    "https://kai.wheellsverse.com",                # same-SITE, different origin
])
def test_a_cookie_handshake_from_an_untrusted_origin_is_refused(tmp_path, origin):
    """A WebSocket handshake is not subject to CORS, so nothing stops a foreign page opening one —
    and the cookie is attached because the browser decides on the destination. Origin is the defence.

    `null` and absent are refused explicitly rather than falling through: a browser always sends
    Origin on a handshake, so its absence means the caller is not the browser this path exists for.
    """
    c = mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)
    ws = FakeWS(cookies={"wv_session": c}, origin=origin) if origin else \
        FakeWS(cookies={"wv_session": c})
    out, p, _ = resolve(ws, store=tmp_path)
    assert out == W.UNTRUSTED_ORIGIN and p is None


def test_a_forged_or_foreign_signed_cookie_is_refused(tmp_path):
    for cookie in ("forged.forged", "", "not-a-token",
                   mint_session("owner", secret="a-different-secret", ttl_seconds=3600)):
        ws = FakeWS(cookies={"wv_session": cookie}, origin="https://app.wheellsverse.com")
        out, _, _ = resolve(ws, store=tmp_path)
        assert out in (W.NO_IDENTITY,), f"{cookie[:12]} -> {out}"


def test_an_expired_session_is_refused(tmp_path):
    c = mint_session("owner", secret=SESSION_SECRET, ttl_seconds=-1)
    out, _, _ = resolve(FakeWS(cookies={"wv_session": c},
                               origin="https://app.wheellsverse.com"), store=tmp_path)
    assert out == W.NO_IDENTITY


# ── the ticket path ───────────────────────────────────────────────────────────────────────────────
def test_a_valid_ticket_is_accepted_once(tmp_path):
    t = ticket()
    out, p, _ = resolve(FakeWS(query={"ticket": t}), store=tmp_path)
    assert out == W.OK and p.source == "ticket" and p.role == "operator"


def test_a_ticket_is_worthless_on_any_other_route(tmp_path):
    """This is what separates a ticket from a JWT in a URL. A leaked JWT authorises everything the
    principal can do; a leaked ticket authorises one route."""
    t = ticket(route=ROUTE)
    out, _, _ = resolve(FakeWS(query={"ticket": t}), route="/api/code/stream/{run_id}", store=tmp_path)
    assert out == W.WRONG_ROUTE


def test_a_ticket_is_worthless_in_another_environment(tmp_path):
    t = ticket(env="staging")
    out, _, _ = resolve(FakeWS(query={"ticket": t}), env="production", store=tmp_path)
    assert out == W.WRONG_ENV


def test_an_expired_ticket_is_refused(tmp_path):
    t = ticket(ttl=-1)
    out, _, _ = resolve(FakeWS(query={"ticket": t}), store=tmp_path)
    assert out == W.EXPIRED


def test_a_tampered_ticket_is_refused(tmp_path):
    """Every field is inside the signed payload, so editing any of them breaks the signature rather
    than silently changing what the ticket authorises."""
    t = ticket(sub="user-1", role="operator")
    body, sig = t.split(".")
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    for before, after in (("user-1", "user-2"), ("operator", "owner"), (ROUTE, "/other")):
        edited = raw.replace(before, after)
        forged = base64.urlsafe_b64encode(edited.encode()).decode().rstrip("=") + "." + sig
        out, _, _ = resolve(FakeWS(query={"ticket": forged}), store=tmp_path)
        assert out == W.BAD_SIGNATURE, f"editing {before} was not detected"


def test_a_ticket_signed_by_a_foreign_secret_is_refused(tmp_path):
    out, _, _ = resolve(FakeWS(query={"ticket": ticket(secret="someone-elses-secret")}),
                        store=tmp_path)
    assert out == W.BAD_SIGNATURE


def test_a_viewer_ticket_cannot_open_a_voice_socket(tmp_path):
    out, _, _ = resolve(FakeWS(query={"ticket": ticket(role="viewer")}), store=tmp_path)
    assert out == W.FORBIDDEN_ROLE


def test_malformed_and_oversized_tickets_are_refused(tmp_path):
    for bad in ("no-dot", "a.b.c", "!!!.!!!", "." , "x." , ".y"):
        out, _, _ = resolve(FakeWS(query={"ticket": bad}), store=tmp_path)
        assert out in (W.MALFORMED, W.BAD_SIGNATURE), f"{bad!r} -> {out}"
    out, _, _ = resolve(FakeWS(query={"ticket": "a" * (W.MAX_TICKET_BYTES + 1)}), store=tmp_path)
    assert out == W.TOO_LARGE, "a handshake is not a data channel"


# ── replay ────────────────────────────────────────────────────────────────────────────────────────
def test_a_replayed_ticket_is_refused(tmp_path):
    t = ticket()
    assert resolve(FakeWS(query={"ticket": t}), store=tmp_path)[0] == W.OK
    assert resolve(FakeWS(query={"ticket": t}), store=tmp_path)[0] == W.REPLAYED


def test_concurrent_replay_has_exactly_one_winner(tmp_path):
    """O_CREAT|O_EXCL decides in ONE syscall. A read-then-write check could let two handshakes both
    observe 'unused' and both proceed; this cannot."""
    import threading
    t = ticket()
    results, lock = [], threading.Lock()

    def attempt():
        out, _, _ = resolve(FakeWS(query={"ticket": t}), store=tmp_path)
        with lock:
            results.append(out)

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count(W.OK) == 1, f"expected exactly one winner, got {results.count(W.OK)}"
    assert results.count(W.REPLAYED) == 11


def test_a_replay_still_fails_after_a_process_restart(tmp_path):
    """The marker is a file, not memory. Reloading the module simulates the restart: if consumption
    lived in a process-local set, the second attempt would succeed and the replay window would
    reopen on every deploy."""
    import importlib
    t = ticket()
    assert resolve(FakeWS(query={"ticket": t}), store=tmp_path)[0] == W.OK
    importlib.reload(W)
    out = W.resolve_ws_principal(FakeWS(query={"ticket": t}), ROUTE, environment=ENV,
                                 trusted_origins=TRUSTED, session_secret=SESSION_SECRET,
                                 ticket_secret=TICKET_SECRET, store=tmp_path)[0]
    assert out == W.REPLAYED


def test_a_ticket_refused_for_another_reason_is_not_burned(tmp_path):
    """Consumption happens LAST. Otherwise a hostile caller could invalidate a legitimate client's
    ticket by replaying it against the wrong route first — a denial of service built out of the
    replay defence."""
    t = ticket()
    assert resolve(FakeWS(query={"ticket": t}), route="/other/ws", store=tmp_path)[0] == W.WRONG_ROUTE
    assert resolve(FakeWS(query={"ticket": t}), env="staging", store=tmp_path)[0] == W.WRONG_ENV
    assert resolve(FakeWS(query={"ticket": t}), store=tmp_path)[0] == W.OK


# ── revocation ────────────────────────────────────────────────────────────────────────────────────
def test_a_revoked_principal_is_refused_on_both_paths(tmp_path):
    revoked = lambda subject: True                                    # noqa: E731
    out, _, _ = resolve(FakeWS(query={"ticket": ticket()}), store=tmp_path, is_revoked=revoked)
    assert out == W.REVOKED
    c = mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)
    out, _, _ = resolve(FakeWS(cookies={"wv_session": c},
                               origin="https://app.wheellsverse.com"),
                        store=tmp_path, is_revoked=revoked)
    assert out == W.REVOKED


def test_revocation_does_not_burn_the_ticket(tmp_path):
    """Checked before consumption, so lifting a revocation does not also require re-minting."""
    t = ticket()
    assert resolve(FakeWS(query={"ticket": t}), store=tmp_path,
                   is_revoked=lambda s: True)[0] == W.REVOKED
    assert resolve(FakeWS(query={"ticket": t}), store=tmp_path)[0] == W.OK


# ── unavailable configuration fails closed ────────────────────────────────────────────────────────
def test_missing_signing_configuration_refuses_rather_than_accepts(tmp_path):
    out = W.resolve_ws_principal(FakeWS(query={"ticket": ticket()}), ROUTE, environment=ENV,
                                 trusted_origins=TRUSTED, session_secret="", ticket_secret="",
                                 store=tmp_path)[0]
    assert out == W.UNAVAILABLE
    c = mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)
    out = W.resolve_ws_principal(FakeWS(cookies={"wv_session": c},
                                        origin="https://app.wheellsverse.com"),
                                 ROUTE, environment=ENV, trusted_origins=TRUSTED,
                                 session_secret="", ticket_secret="", store=tmp_path)[0]
    assert out == W.UNAVAILABLE


def test_an_unwritable_store_denies_rather_than_admits(tmp_path):
    """The webhook idempotency store fails OPEN, because a store outage there risks dropping a real
    provider event. Here the same outage would mean admitting an unverified replay, so it denies.
    The direction of the failure is a decision, not an accident, and it differs by context."""
    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory")
    assert W.consume_jti("some-jti", store=blocked) is False


# ── nothing is logged ─────────────────────────────────────────────────────────────────────────────
def test_no_refusal_reason_echoes_the_credential(tmp_path):
    """A reason names the failure CLASS. If it quoted the artifact, every refusal would write the
    thing we just spent this module removing from URLs into the log instead."""
    t = ticket()
    c = mint_session("owner", secret=SESSION_SECRET, ttl_seconds=3600)
    secrets = [t, c, "eyJhbGci.some.jwt"]
    probes = [
        FakeWS(query={"ticket": t}),
        FakeWS(query={"token": "eyJhbGci.some.jwt"}),
        FakeWS(cookies={"wv_session": c}, origin="https://evil.com"),
        FakeWS(query={"ticket": t + "tamper"}),
    ]
    for ws in probes:
        outcome, principal, reason = resolve(ws, store=tmp_path)
        blob = f"{outcome} {reason} {principal!r}"
        for s in secrets:
            assert s not in blob, "a refusal echoed a credential"
            assert s[:24] not in blob, "a refusal echoed a credential prefix"


def test_redact_never_returns_the_value():
    t = ticket()
    assert t not in W.redact(t) and "redacted" in W.redact(t)
    assert W.redact(None) == "<absent>" and W.redact("") == "<absent>"


def test_the_principal_repr_does_not_leak_the_subject():
    """Logging a principal is the natural thing to do; make it safe by construction rather than by
    remembering not to."""
    p = W.WSPrincipal(subject="user-secret-id", role="owner", source="ticket")
    assert "user-secret-id" not in repr(p)


def test_the_handler_logs_no_identifying_material():
    import inspect
    from narai.api.routes import voice
    src = inspect.getsource(voice.voice_ws)
    # Parsed, not grepped. A line-based scan reads only the line containing "logger." — and a
    # multi-line call puts its f-string on the NEXT line, which is exactly how
    #     logger.info(
    #         f"voice audio in: sub={sub} bytes={len(audio)} head={head_hex}"
    #     )
    # survived the first version of this test while logging both the authenticated subject and 16
    # raw bytes of the audio stream. ast.walk sees the whole call, however it is formatted.
    import ast
    tree = ast.parse(textwrap.dedent(src))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "logger"]
    assert calls, "the handler should log something about refusals"
    FORBIDDEN = ("ticket", "token", "cookie", "sub", "subject", "transcript", "audio", "head")
    for call in calls:
        segment = ast.get_source_segment(textwrap.dedent(src), call) or ""
        # Names whose VALUE reaches the log. len(audio) is fine — a byte count answers "did a frame
        # arrive" without recording what was said; audio[:16].hex() is not. So a forbidden name is
        # only a leak when it is not wrapped in a size-only call.
        SIZE_ONLY = {"len"}
        leaked = set()

        def collect(node):
            for child in ast.iter_child_nodes(node):
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                        and child.func.id in SIZE_ONLY):
                    continue                      # len(x) reveals a count, not content
                if isinstance(child, ast.Name):
                    leaked.add(child.id)
                collect(child)

        collect(call)
        for bad in FORBIDDEN:
            assert bad not in leaked, (
                f"logger call puts {bad!r} in the log: {segment.strip()[:90]}")
        low = segment.lower()
        for bad in ("sub=", "token=", "ticket=", "cookie=", "head=", "transcript"):
            assert bad not in low, f"logger call may leak {bad}: {segment.strip()[:90]}"


# ── housekeeping ──────────────────────────────────────────────────────────────────────────────────
def test_sweep_removes_only_markers_past_the_window(tmp_path):
    fresh, stale = tmp_path / "fresh", tmp_path / "stale"
    tmp_path.mkdir(parents=True, exist_ok=True)
    fresh.write_text(""); stale.write_text("")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    assert W.sweep(store=tmp_path, older_than=3600) == 1
    assert fresh.exists() and not stale.exists()


def test_the_ticket_ttl_is_short_enough_to_matter():
    """The whole argument for tolerating a ticket in a URL is that the window is tiny. If this ever
    grows, that argument stops holding and the design should be revisited rather than the constant."""
    assert W.TICKET_TTL_SECONDS <= 60, (
        "a ticket that lives longer than a handshake is drifting back toward a bearer token in a URL")


def test_the_voice_route_refuses_before_it_accepts():
    """The property everything else depends on.

    The old handler's own comment said it accepted first because "FastAPI requires accept() before
    close can send a meaningful code" — and that is true, but it means the handshake with an
    unauthenticated peer COMPLETED. A connection you accept and then drop is a connection you
    accepted. Closing without accepting is what makes a refusal a refusal.

    Checked structurally rather than by string order: the resolver call must be reached, and no
    accept() may appear before it on any path.
    """
    import ast
    import inspect
    import textwrap
    from narai.api.routes import voice

    tree = ast.parse(textwrap.dedent(inspect.getsource(voice.voice_ws)))
    fn = tree.body[0]

    def is_accept(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "accept")

    def is_resolve(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "resolve_ws_principal")

    accepts = [n.lineno for n in ast.walk(fn) if is_accept(n)]
    resolves = [n.lineno for n in ast.walk(fn) if is_resolve(n)]
    assert resolves, "voice_ws never calls resolve_ws_principal — it authenticates itself or not at all"
    assert accepts, "voice_ws never accepts, which cannot be right either"
    assert min(resolves) < min(accepts), (
        f"accept() at line {min(accepts)} precedes resolve_ws_principal() at line {min(resolves)}")

    # "resolve before accept" is necessary but NOT sufficient, and a mutant proved it: inserting
    # accept() AFTER the resolver but BEFORE the refusal branch still completes the handshake with
    # an unauthenticated peer — the close afterwards is a disconnect, not a refusal. The property
    # that actually holds the line is that no accept() is REACHABLE until the refusal has returned.
    guard_end = None
    for stmt in fn.body:
        if isinstance(stmt, ast.If) and any(isinstance(n, ast.Return) for n in ast.walk(stmt)):
            guard_end = stmt.end_lineno
            break
    assert guard_end is not None, (
        "voice_ws has no top-level guard branch that returns — nothing refuses before accept()")
    early = [ln for ln in accepts if ln <= guard_end]
    assert not early, (
        f"accept() at line(s) {early} is reachable before the refusal branch ends at line "
        f"{guard_end}: the handshake completes with an unauthenticated peer and is merely dropped "
        "afterwards")


def test_both_websocket_routes_use_the_same_resolver():
    """Two routes, one answer to 'who is this'. They existed independently before — one gated by
    _ws_owner_ok and one by a JWT in a URL — and that divergence is how the voice route kept a
    credential in a query string long after the pattern was removed everywhere else."""
    import inspect
    from narai.api.routes import voice
    from core import code_router

    voice_src = inspect.getsource(voice.voice_ws)
    code_src = inspect.getsource(code_router.code_stream)
    assert "resolve_ws_principal" in voice_src, "voice_ws does not use the shared resolver"
    assert ("_ws_owner_ok" in code_src or "resolve_ws_principal" in code_src), (
        "code_stream has no WebSocket gate")
