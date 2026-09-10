"""The one authoritative WebSocket principal resolver. Pure stdlib apart from the nonce marker.

WHY THIS EXISTS. /api/v2/narai/voice/ws authenticated with a long-lived JWT taken from a QUERY
PARAMETER:

    async def voice_ws(websocket, token: str = Query(..., description="JWT from /auth/login")):
        sub = _verify_token(token)

That is a reusable production credential in a URL. A URL is not a private channel: it lands in
Cloudflare edge logs, Railway access logs, any intermediary proxy, browser history, and Referer
headers sent to third parties — none of which it can be revoked from. This codebase already removed
exactly this pattern once, when `?api_key=` was deleted from core/operator_session_web.py, and the
reason recorded there applies unchanged here.

It was also the ONE route the HTTP gate never saw. api_key_middleware is @app.middleware("http") and
Starlette passes non-HTTP scopes straight through, so every WebSocket route authenticates itself or
not at all. There are now two, they must not drift, and this module is the single place either of
them asks "who is this".

TWO ACCEPTED IDENTITIES, and nothing else.

  1. SESSION COOKIE — the browser path. HttpOnly, Secure, SameSite=Lax, already minted by
     /admin/session/login. A browser cannot set headers on a WebSocket handshake, which is the real
     reason the JWT ended up in the URL; a cookie needs no header. Because a WebSocket handshake is
     NOT subject to CORS, nothing stops a foreign page opening one and the cookie is attached anyway
     — that is cross-site WebSocket hijacking, so an exact trusted Origin is required.

  2. SINGLE-USE TICKET — for clients that cannot present the cookie. The client POSTs over HTTPS
     with its normal bearer JWT, gets a ticket bound to (principal, route, environment, expiry, jti),
     and spends it once. The bearer JWT never appears in a URL.

     A ticket in a URL is not equivalent to a JWT in a URL and this module does not pretend it is.
     A leaked ticket is useless: it expires in TICKET_TTL_SECONDS, it is bound to one route and one
     environment, and consumption is atomic so the second use loses. A leaked JWT is a standing
     credential. The mitigation is that the window is small and the artifact is worthless afterwards
     — not that logging it is fine.

THE LEGACY PARAMETER IS REFUSED, NOT IGNORED. `?token=` is rejected explicitly rather than simply
going unread, so a client that still sends one gets a hard failure instead of silently falling
through to some other path. A credential that stops being checked but keeps being transmitted is
worse than one that is checked.

REPLAY SURVIVES RESTART. Consumption is a filesystem claim: O_CREAT|O_EXCL either creates the marker
or fails EEXIST, one syscall, so two concurrent handshakes cannot both win, and the marker outlives
the process. On Railway the store lives on the mounted volume (RAILWAY_VOLUME_MOUNT_PATH=/var/data),
so it survives redeploys too. It is per-instance: with more than one replica a ticket could be spent
once per replica, which is why TICKET_TTL_SECONDS is 30 and not 3600.

NOTHING HERE IS LOGGED. No ticket, no JWT, no cookie, no jti. redact() exists so callers cannot
accidentally put one in a log line, and every refusal returns a reason string that names the failure
class without echoing the artifact.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

TICKET_VERSION = "1"
TICKET_TTL_SECONDS = 30          # deliberately tiny: the ticket only has to survive the handshake
MAX_TICKET_BYTES = 512           # bounded metadata — a handshake is not a data channel
LEGACY_PARAM = "token"
TICKET_PARAM = "ticket"

# Outcomes. Each names a failure CLASS; none echoes the artifact.
OK = "OK"
NO_IDENTITY = "WS_NO_IDENTITY"
LEGACY_JWT_IN_URL = "WS_LEGACY_JWT_QUERY_PARAM_REFUSED"
MALFORMED = "WS_TICKET_MALFORMED"
BAD_SIGNATURE = "WS_TICKET_SIGNATURE_INVALID"
EXPIRED = "WS_TICKET_EXPIRED"
WRONG_ROUTE = "WS_TICKET_ROUTE_MISMATCH"
WRONG_ENV = "WS_TICKET_ENVIRONMENT_MISMATCH"
REPLAYED = "WS_TICKET_ALREADY_CONSUMED"
UNTRUSTED_ORIGIN = "WS_ORIGIN_NOT_TRUSTED"
FORBIDDEN_ROLE = "WS_ROLE_LACKS_PERMISSION"
REVOKED = "WS_PRINCIPAL_REVOKED"
UNAVAILABLE = "WS_AUTH_UNAVAILABLE"
TOO_LARGE = "WS_METADATA_TOO_LARGE"

# Roles allowed to open a voice socket. A viewer or the release verifier may READ the estate; neither
# may open a live microphone channel that spends money and speaks as the owner.
VOICE_ROLES = frozenset({"owner", "operator"})

_STORE = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "data")) / "ws_tickets"


def redact(value: Optional[str]) -> str:
    """What a log line is allowed to contain about a credential: that it existed, and its shape."""
    if not value:
        return "<absent>"
    return f"<redacted:{len(value)}b>"


@dataclass(frozen=True)
class WSPrincipal:
    subject: str
    role: str
    source: str          # "session" | "ticket"
    def __repr__(self) -> str:                      # never let a repr leak the subject wholesale
        return f"WSPrincipal(role={self.role!r}, source={self.source!r})"


# ── ticket minting and verification (pure) ────────────────────────────────────────────────────────
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def mint_ticket(subject: str, role: str, route: str, environment: str, secret: str,
                ttl_seconds: int = TICKET_TTL_SECONDS, now: Optional[float] = None) -> str:
    """A ticket authorises ONE principal, on ONE route, in ONE environment, once, for TTL seconds.

    Every field is inside the signed payload, so none of them can be edited in transit. The jti is
    what makes it single-use; it is random rather than derived so two tickets minted in the same
    second for the same subject cannot collide.
    """
    if not secret:
        raise ValueError("no signing secret")
    issued = int(time.time() if now is None else now)
    jti = _b64(os.urandom(16))
    payload = "|".join([TICKET_VERSION, subject, role, route, environment,
                        str(issued + ttl_seconds), jti])
    return f"{_b64(payload.encode())}.{_sign(payload, secret)}"


def verify_ticket(ticket: Optional[str], route: str, environment: str, secret: str,
                  now: Optional[float] = None) -> Tuple[str, Optional[WSPrincipal], Optional[str]]:
    """(outcome, principal, jti). Pure — consumption is a separate, atomic step.

    Split deliberately: verifying and consuming are different failures with different meanings, and
    a caller must not be able to consume a ticket it has not verified, nor accept one it has not
    consumed.
    """
    if not secret:
        return UNAVAILABLE, None, None
    if not ticket:
        return NO_IDENTITY, None, None
    if len(ticket) > MAX_TICKET_BYTES:
        return TOO_LARGE, None, None
    if ticket.count(".") != 1:
        return MALFORMED, None, None
    body, sig = ticket.split(".", 1)
    try:
        payload = _unb64(body).decode()
    except Exception:
        return MALFORMED, None, None
    if not hmac.compare_digest(sig, _sign(payload, secret)):
        return BAD_SIGNATURE, None, None
    parts = payload.split("|")
    if len(parts) != 7 or parts[0] != TICKET_VERSION:
        return MALFORMED, None, None
    _v, subject, role, t_route, t_env, exp_s, jti = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return MALFORMED, None, None
    # Route and environment are checked BEFORE expiry so a ticket minted for another route reports
    # that, rather than the less useful "expired", once it ages out.
    if not hmac.compare_digest(t_route, route):
        return WRONG_ROUTE, None, None
    if not hmac.compare_digest(t_env, environment):
        return WRONG_ENV, None, None
    if (time.time() if now is None else now) > exp:
        return EXPIRED, None, None
    if role not in VOICE_ROLES:
        return FORBIDDEN_ROLE, None, None
    return OK, WSPrincipal(subject=subject, role=role, source="ticket"), jti


def consume_jti(jti: str, store: Optional[Path] = None) -> bool:
    """True iff this call is the one that claimed the ticket. Atomic, and survives restart.

    O_CREAT|O_EXCL decides in a single syscall, so concurrent handshakes cannot both win — a
    read-then-write check could. The marker is a file on the mounted volume, so a redeploy does not
    reopen the replay window.

    Fails CLOSED, unlike the webhook idempotency store: there, a store outage risked dropping a real
    provider event; here it would mean accepting an unverified replay, so an unwritable store denies.
    """
    if not jti:
        return False
    root = store or _STORE
    marker = root / hashlib.sha256(jti.encode()).hexdigest()[:32]
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False        # replay
        return False            # store unavailable -> deny
    os.close(fd)
    return True


def sweep(store: Optional[Path] = None, older_than: int = 3600) -> int:
    """Drop markers older than a ticket could possibly be. Cheap, and keeps the dir from growing."""
    root = store or _STORE
    if not root.exists():
        return 0
    cutoff, removed = time.time() - older_than, 0
    for p in root.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


# ── origin ────────────────────────────────────────────────────────────────────────────────────────
def origin_ok(origin: Optional[str], allowed: frozenset) -> bool:
    """Exact origin match. A handshake is never a safe method, so there is no read-only exemption.

    `null` (sandboxed iframe, data: URL, some redirect chains) is a real value an attacker can
    produce and never appears in an allowlist, so it fails here without a special case. Absent is
    also refused: a browser always sends Origin on a WebSocket handshake, so its absence means the
    caller is not the browser this path exists for.
    """
    if not origin:
        return False
    try:
        from urllib.parse import urlsplit
        u = urlsplit(origin.strip())
        if not u.scheme or not u.hostname:
            return False
        host = u.hostname.lower() + (f":{u.port}" if u.port else "")
        return f"{u.scheme.lower()}://{host}" in allowed
    except Exception:
        return False


# ── the authoritative resolver ────────────────────────────────────────────────────────────────────
def resolve_ws_principal(websocket, route: str, *, environment: Optional[str] = None,
                         trusted_origins: Optional[frozenset] = None,
                         session_secret: Optional[str] = None,
                         ticket_secret: Optional[str] = None,
                         is_revoked=None,
                         store: Optional[Path] = None) -> Tuple[str, Optional[WSPrincipal], str]:
    """(outcome, principal, reason). MUST be called before websocket.accept().

    Accepting an unauthenticated peer and closing afterwards still completes a handshake with them,
    and the old voice route did exactly that — its comment even explained why. A refusal has to
    happen first.
    """
    env = environment or os.getenv("APP_ENV", "production").strip().lower()

    qp = dict(websocket.query_params) if hasattr(websocket, "query_params") else {}

    # Refused explicitly, not ignored: a client still sending a standing JWT in a URL must fail
    # loudly so it gets fixed, rather than silently falling through to the cookie path.
    if LEGACY_PARAM in qp:
        return LEGACY_JWT_IN_URL, None, ("a JWT in a query parameter is refused; POST for a "
                                         "single-use ticket or use the session cookie")

    headers = getattr(websocket, "headers", {}) or {}
    origin = headers.get("origin")
    allowed = trusted_origins if trusted_origins is not None else frozenset()

    # ── path 1: the session cookie ──
    cookies = getattr(websocket, "cookies", {}) or {}
    session_cookie = cookies.get("wv_session")
    if session_cookie:
        if not origin_ok(origin, allowed):
            return UNTRUSTED_ORIGIN, None, "cookie handshake from an untrusted or absent Origin"
        if not session_secret:
            return UNAVAILABLE, None, "session signing secret not configured"
        try:
            from core.operator_session import verify_session
            principal = verify_session(session_cookie, secret=session_secret)
        except Exception:
            principal = None
        if principal is None:
            # verify_session already fails closed on bad shape, bad signature, expiry and unknown
            # role, so there is nothing to re-check here — only to not paper over the None.
            return NO_IDENTITY, None, "session cookie invalid or expired"
        role = principal.role
        # The unified session is ROLE-based, not user-based: it carries no subject claim, and
        # principal_for_role builds it from the role alone. So the role IS the identity on this path,
        # and pretending otherwise by inventing a subject would make the audit trail lie.
        subject = f"session:{role}"
        if role not in VOICE_ROLES:
            return FORBIDDEN_ROLE, None, f"role {role!r} may not open a voice socket"
        if is_revoked and is_revoked(subject):
            return REVOKED, None, "principal revoked"
        return OK, WSPrincipal(subject=subject, role=role, source="session"), "session cookie"

    # ── path 2: the single-use ticket ──
    ticket = qp.get(TICKET_PARAM)
    if not ticket:
        return NO_IDENTITY, None, "no session cookie and no ticket"
    outcome, principal, jti = verify_ticket(ticket, route=route, environment=env,
                                            secret=ticket_secret or "")
    if outcome != OK or principal is None or not jti:
        return outcome, None, f"ticket rejected ({outcome})"
    if is_revoked and is_revoked(principal.subject):
        return REVOKED, None, "principal revoked"
    # Consumed LAST and atomically: a ticket rejected for any other reason must not be burned, or a
    # hostile caller could invalidate a legitimate client's ticket by replaying it against the wrong
    # route first.
    if not consume_jti(jti, store=store):
        return REPLAYED, None, "ticket already consumed"
    return OK, principal, "single-use ticket"


def demo() -> None:
    """Zero-framework self-check: python3 narai/api/ws_auth.py"""
    import tempfile
    import types

    SEC, ROUTE, ENV = "ticket-secret", "/api/v2/narai/voice/ws", "production"
    ALLOWED = frozenset({"https://app.wheellsverse.com"})

    def ws(query=None, cookies=None, origin=None):
        return types.SimpleNamespace(
            query_params=query or {},
            cookies=cookies or {},
            headers={"origin": origin} if origin else {},
        )

    # ── ticket: bound to principal, role, route, environment, expiry ──
    t = mint_ticket("user-1", "owner", ROUTE, ENV, SEC)
    assert verify_ticket(t, ROUTE, ENV, SEC)[0] == OK
    assert verify_ticket(t, "/other/ws", ENV, SEC)[0] == WRONG_ROUTE
    assert verify_ticket(t, ROUTE, "staging", SEC)[0] == WRONG_ENV
    assert verify_ticket(t, ROUTE, ENV, "wrong-secret")[0] == BAD_SIGNATURE
    assert verify_ticket(t, ROUTE, ENV, SEC, now=time.time() + 9999)[0] == EXPIRED
    assert verify_ticket(None, ROUTE, ENV, SEC)[0] == NO_IDENTITY
    assert verify_ticket("no-dot", ROUTE, ENV, SEC)[0] == MALFORMED
    assert verify_ticket("a" * (MAX_TICKET_BYTES + 1), ROUTE, ENV, SEC)[0] == TOO_LARGE
    assert verify_ticket(t, ROUTE, ENV, "")[0] == UNAVAILABLE
    # a viewer cannot get a usable voice ticket even with a valid signature
    assert verify_ticket(mint_ticket("u", "viewer", ROUTE, ENV, SEC), ROUTE, ENV, SEC)[0] == FORBIDDEN_ROLE
    # editing any field breaks the signature
    body, sig = t.split(".")
    tampered = _b64(_unb64(body).decode().replace("user-1", "user-2").encode()) + "." + sig
    assert verify_ticket(tampered, ROUTE, ENV, SEC)[0] == BAD_SIGNATURE

    # ── single use, atomic, survives "restart" (a fresh call against the same dir) ──
    with tempfile.TemporaryDirectory() as d:
        store = Path(d)
        _, _, jti = verify_ticket(t, ROUTE, ENV, SEC)
        assert consume_jti(jti, store) is True
        assert consume_jti(jti, store) is False          # replay
        assert consume_jti("", store) is False           # no jti is not claimable
        assert consume_jti(_b64(os.urandom(16)), store) is True

    # ── resolver: legacy param refused explicitly ──
    out, p, _ = resolve_ws_principal(ws(query={"token": "a.jwt.here"}), ROUTE,
                                     environment=ENV, trusted_origins=ALLOWED,
                                     ticket_secret=SEC)
    assert out == LEGACY_JWT_IN_URL and p is None
    # even alongside a valid ticket — the presence of the legacy param is itself the failure
    out, _, _ = resolve_ws_principal(ws(query={"token": "x", "ticket": t}), ROUTE,
                                     environment=ENV, trusted_origins=ALLOWED, ticket_secret=SEC)
    assert out == LEGACY_JWT_IN_URL

    with tempfile.TemporaryDirectory() as d:
        store = Path(d)
        fresh = mint_ticket("user-9", "operator", ROUTE, ENV, SEC)
        out, p, _ = resolve_ws_principal(ws(query={"ticket": fresh}), ROUTE, environment=ENV,
                                         trusted_origins=ALLOWED, ticket_secret=SEC, store=store)
        assert out == OK and p.source == "ticket" and p.role == "operator"
        # exactly one winner
        out2, _, _ = resolve_ws_principal(ws(query={"ticket": fresh}), ROUTE, environment=ENV,
                                          trusted_origins=ALLOWED, ticket_secret=SEC, store=store)
        assert out2 == REPLAYED
        # a ticket refused for the wrong route must NOT be burned
        other = mint_ticket("user-9", "owner", ROUTE, ENV, SEC)
        assert resolve_ws_principal(ws(query={"ticket": other}), "/other/ws", environment=ENV,
                                    trusted_origins=ALLOWED, ticket_secret=SEC, store=store)[0] == WRONG_ROUTE
        assert resolve_ws_principal(ws(query={"ticket": other}), ROUTE, environment=ENV,
                                    trusted_origins=ALLOWED, ticket_secret=SEC, store=store)[0] == OK

    # ── no identity at all ──
    assert resolve_ws_principal(ws(), ROUTE, environment=ENV, trusted_origins=ALLOWED,
                                ticket_secret=SEC)[0] == NO_IDENTITY

    # ── origin ──
    assert origin_ok("https://app.wheellsverse.com", ALLOWED) is True
    for bad in (None, "", "null", "https://evil.com", "https://app.wheellsverse.com.evil.com",
                "http://app.wheellsverse.com", "https://app.wheellsverse.com:8443"):
        assert origin_ok(bad, ALLOWED) is False, bad

    # ── redaction ──
    assert redact(None) == "<absent>" and t not in redact(t) and "redacted" in redact(t)

    print("ws_auth: all checks passed")


if __name__ == "__main__":
    demo()
