"""Owner sign-in for the daily numbers board and every /admin page.

Sign-in checks the owner's email and password with ONE stateless HTTP password
grant to Supabase Auth, using the anon key (the approach of
backend/app/services/supabase_auth.py, copied rather than imported: core/api.py
never loads backend/app). No supabase-py client ever signs in, so the shared
service-role client in core/narai_user.py never holds a user session. The
returned user id must equal BOARD_OWNER_USER_ID.

The browser then holds a random 32-byte token in the __Host-board_session
cookie (HttpOnly, Secure, SameSite=Lax, Path=/, no Domain). Only the token's
SHA-256 is stored, in public.owner_sessions
(narai/migrations/0002_daily_numbers_board.sql), read and written over
PostgREST with the service-role key and a short timeout. A session lasts 7
days; sign-out revokes its row at once. A valid session is cached in this
process for at most 60 seconds, and sign-out drops it from the cache.

Fails closed: while BOARD_OWNER_USER_ID, SUPABASE_URL, SUPABASE_ANON_KEY or
SUPABASE_SERVICE_KEY is unset (or unusable), sign-in and every gated route
answer 503.

Setup: in Supabase Auth the Email provider is on and the owner's email is
confirmed; SUPABASE_ANON_KEY is this same project's anon (or publishable) key.
Supabase's answers that point at the setup rather than the password are logged
with their error code.

Sign-in limits (in memory): failed attempts back off per client address and per
email, and an attempt counts from the moment it starts, so parallel attempts
cannot slip past the count. A successful sign-in also sets a known-device cookie
(__Host-board_device, a random id signed with a key derived from the
service-role key; it opens nothing by itself). A browser that presents it is
limited by its own failures only, so nobody else's failures, with the owner's
email or from any client address, can hold the owner back there.

Gates:
  * AdminPageGate (ASGI middleware): every path that starts with /admin.
    Without a session a page answers 302 to /board/login?next=<path>; any
    other route answers 401. The admin pages are static files, the same bytes
    for every visitor, with nothing secret in them.
  * require_owner: the dependency on every /api/board/* route.
  * api_cookie_denial (api_key_middleware) and owner_session_allows (the
    admin API routers): a signed-in owner's admin pages call the X-API-Key
    routes with the session cookie instead of a key.

A request authenticated by the cookie must come from this site's own pages: a
write (POST, PUT, PATCH, DELETE) needs an Origin header (or, without one, a
Referer) equal to the app's own origin, and a read that the browser marks as
coming from another origin is refused. So no other origin can use the owner's
session, even one that the CORS settings allow to send credentials.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import re
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlsplit

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

log = logging.getLogger("board.auth")

SESSION_COOKIE = "__Host-board_session"
SESSION_DAYS = 7
DEVICE_COOKIE = "__Host-board_device"
DEVICE_DAYS = 365
LOGIN_PATH = "/board/login"
DEFAULT_NEXT = "/admin/scoreboard"

_HTTP_TIMEOUT = 5.0     # seconds, each owner_sessions read or write
_GRANT_TIMEOUT = 10.0   # seconds, the one password grant per sign-in
_CACHE_SECONDS = 60.0   # a valid session is read again at least this often
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")   # secrets.token_urlsafe(32)
_DEVICE_RE = re.compile(r"^([A-Za-z0-9_-]{22})\.([0-9]{1,12})\.([0-9a-f]{64})$")   # id.issued.mac
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_NO_STORE = {"Cache-Control": "no-store"}

# Tests put an httpx.MockTransport here; None means the real network.
_transport: Optional[httpx.BaseTransport] = None
# Clock for the session cache and the sign-in backoff (tests move it forward).
_now = time.monotonic
# Wall clock for the known-device cookie's age (tests move it forward).
_wall = time.time


class SignInError(Exception):
    """A refused sign-in. `status` and `message` go back to the browser."""

    def __init__(self, status: int, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


class SessionStoreError(Exception):
    """owner_sessions could not be read or written."""


# ─── settings ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BoardSettings:
    url: str
    anon_key: str
    service_key: str
    owner_id: str


def _uuid_or_none(value) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


_warned: set = set()


def _usable_url(url: str) -> bool:
    """An http(s) URL with a host and a valid port. A copy-paste can leave an
    invisible character or a bad port in it, and httpx then fails every call."""
    try:
        parsed = httpx.URL(url)
        port = parsed.port
    except (httpx.InvalidURL, ValueError, TypeError):
        return False
    return (parsed.scheme in ("http", "https") and bool(parsed.host)
            and not any(c.isspace() for c in url) and (port is None or 0 < port < 65536))


def board_settings() -> Optional[BoardSettings]:
    """What sign-in needs, read at call time. None while any of it is unset or
    unusable (the owner id not a uuid, the URL not an http(s) URL, a key that an
    HTTP header cannot carry): the board is closed."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
    service = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    owner_raw = os.getenv("BOARD_OWNER_USER_ID", "").strip()
    owner = _uuid_or_none(owner_raw) if owner_raw else None
    problems = []
    if owner_raw and owner is None:
        problems.append("BOARD_OWNER_USER_ID is not a uuid")
    if url and not _usable_url(url):
        problems.append("SUPABASE_URL is not a usable http(s) URL")
    for name, key in (("SUPABASE_ANON_KEY", anon), ("SUPABASE_SERVICE_KEY", service)):
        if not (key.isascii() and key.isprintable()):
            problems.append(f"{name} has characters an HTTP header cannot carry")
    for problem in problems:
        if problem not in _warned:
            _warned.add(problem)
            log.warning("%s; the board stays closed", problem)
    if problems or not (url and anon and service and owner):
        return None
    return BoardSettings(url=url, anon_key=anon, service_key=service, owner_id=owner)


# ─── HTTP to Supabase (Auth and PostgREST) ──────────────────────────────────

def _http(method: str, url: str, *, timeout: float, **kwargs) -> httpx.Response:
    with httpx.Client(transport=_transport, timeout=timeout) as client:
        return client.request(method, url, **kwargs)


def _error_code(r: httpx.Response) -> str:
    """GoTrue's error code (error_code, or the older `error`), safe to log. Only
    error bodies are read here: a 200 carries tokens and is never logged."""
    try:
        body = r.json()
    except ValueError:
        body = None
    code = (body.get("error_code") or body.get("error")) if isinstance(body, dict) else None
    return re.sub(r"[^a-z0-9_]", "", str(code or "").lower())[:40] or "none"


def password_grant(cfg: BoardSettings, email: str, password: str) -> Optional[str]:
    """One stateless password grant with the anon key. Returns the Supabase user
    id, or None when the email or password is wrong. The tokens Supabase returns
    are dropped: the board keeps its own session."""
    try:
        r = _http("POST", f"{cfg.url}/auth/v1/token", timeout=_GRANT_TIMEOUT,
                  params={"grant_type": "password"},
                  headers={"apikey": cfg.anon_key, "Content-Type": "application/json"},
                  json={"email": email, "password": password})
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        log.warning("board sign-in: Supabase Auth unreachable (%s)", type(e).__name__)
        raise SignInError(502, "The sign-in service is unreachable. Try again shortly.") from None
    if r.status_code == 200:
        try:
            user_id = _uuid_or_none(((r.json() or {}).get("user") or {}).get("id"))
        except (ValueError, AttributeError):
            user_id = None
        if user_id is None:
            log.warning("board sign-in: Supabase Auth returned no user id")
            raise SignInError(502, "The sign-in service answered without a user.")
        return user_id
    if r.status_code == 429:
        raise SignInError(429, "Too many sign-in attempts. Try again later.", retry_after=60)
    if r.status_code in (401, 403):
        # The gateway refused the server's key (another project's, rotated, or
        # turned off), not the owner's password.
        log.warning("board sign-in: Supabase Auth refused the anon key (HTTP %s, %s); check "
                    "SUPABASE_URL and SUPABASE_ANON_KEY", r.status_code, _error_code(r))
        raise SignInError(502, "The sign-in service refused this server's settings.")
    if r.status_code in (400, 422):
        code = _error_code(r)
        if code not in ("invalid_credentials", "invalid_grant"):
            # email_not_confirmed, email_provider_disabled, ...: a setup problem
            log.warning("board sign-in: Supabase Auth refused the grant (HTTP %s, %s)", r.status_code, code)
        return None   # one answer for all of them in the browser
    log.warning("board sign-in: Supabase Auth answered HTTP %s", r.status_code)
    raise SignInError(502, "The sign-in service failed. Try again shortly.")


def _rest(cfg: BoardSettings, method: str, *, params: Optional[dict] = None,
          json: Optional[dict] = None, prefer: Optional[str] = None) -> httpx.Response:
    """owner_sessions over PostgREST, with the service-role key (RLS is on with
    no policies, so no other key can read the table)."""
    headers = {"apikey": cfg.service_key, "Authorization": f"Bearer {cfg.service_key}",
               "Accept": "application/json"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    try:
        return _http(method, f"{cfg.url}/rest/v1/owner_sessions", timeout=_HTTP_TIMEOUT,
                     params=params, json=json, headers=headers)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise SessionStoreError(type(e).__name__) from None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _hash_filter(token_hash: str) -> str:
    return "eq.\\x" + token_hash          # bytea as Postgres hex text


def _parse_ts(value) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ─── session cache (this process only, at most 60 s) ────────────────────────

_cache_lock = threading.Lock()
_valid: dict[str, tuple[str, float]] = {}   # token hash -> (user id, clock deadline)
_revoked: dict[str, float] = {}             # token hash -> clock deadline (signed out here)


def _cache_get(token_hash: str) -> Optional[str]:
    now = _now()
    with _cache_lock:
        if _revoked.get(token_hash, 0.0) > now:
            return None
        hit = _valid.get(token_hash)
        if hit and hit[1] > now:
            return hit[0]
        _valid.pop(token_hash, None)
        return None


def _cache_put(token_hash: str, user_id: str, seconds: float) -> None:
    now = _now()
    with _cache_lock:
        if _revoked.get(token_hash, 0.0) > now:
            return
        if len(_valid) > 1000:
            for k in [k for k, (_, until) in _valid.items() if until <= now]:
                del _valid[k]
            if len(_valid) > 1000:
                _valid.clear()
        _valid[token_hash] = (user_id, now + max(0.0, min(_CACHE_SECONDS, seconds)))


def _revoked_here(token_hash: str) -> bool:
    with _cache_lock:
        return _revoked.get(token_hash, 0.0) > _now()


def _cache_revoke(token_hash: str) -> None:
    now = _now()
    with _cache_lock:
        _valid.pop(token_hash, None)
        for k in [k for k, until in _revoked.items() if until <= now]:
            del _revoked[k]
        _revoked[token_hash] = now + _CACHE_SECONDS


def _cache_unrevoke(token_hash: str) -> None:
    with _cache_lock:
        _revoked.pop(token_hash, None)


def reset_state() -> None:
    """Forget cached sessions and sign-in failures (tests; a key rotation)."""
    with _cache_lock:
        _valid.clear()
        _revoked.clear()
    _ip_backoff.reset()
    _email_backoff.reset()
    _device_backoff.reset()


# ─── sessions ───────────────────────────────────────────────────────────────

def create_session(cfg: BoardSettings, user_id: str, user_agent: str = "") -> str:
    """Store a new 7-day session (its hash only) and return the token."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    agent = "".join(c for c in (user_agent or "") if c.isprintable())[:300] or None
    r = _rest(cfg, "POST", prefer="return=minimal",
              json={"token_sha256": "\\x" + _token_hash(token), "user_id": user_id,
                    "expires_at": expires.isoformat(), "user_agent": agent})
    if r.status_code not in (200, 201, 204):
        log.warning("board sign-in: owner_sessions insert answered HTTP %s", r.status_code)
        raise SessionStoreError(f"insert HTTP {r.status_code}")
    return token


def session_user(cfg: BoardSettings, token: Optional[str]) -> Optional[str]:
    """The owner's user id when `token` is a live owner session, else None.
    Raises SessionStoreError when owner_sessions cannot be read."""
    if not token or not _TOKEN_RE.match(token):
        return None
    token_hash = _token_hash(token)
    if _revoked_here(token_hash):
        return None
    cached = _cache_get(token_hash)
    if cached is not None:
        return cached if cached == cfg.owner_id else None
    r = _rest(cfg, "GET", params={"select": "user_id,expires_at,revoked_at",
                                  "token_sha256": _hash_filter(token_hash), "limit": "1"})
    if r.status_code != 200:
        raise SessionStoreError(f"read HTTP {r.status_code}")
    try:
        rows = r.json()
    except ValueError:
        raise SessionStoreError("read: not JSON") from None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    if row.get("revoked_at"):
        return None
    expires = _parse_ts(row.get("expires_at"))
    left = (expires - datetime.now(timezone.utc)).total_seconds() if expires else 0.0
    if left <= 0 or _uuid_or_none(row.get("user_id")) != cfg.owner_id:
        return None
    _cache_put(token_hash, cfg.owner_id, left)
    # Signed out here while this read was in flight: the read is stale.
    return None if _revoked_here(token_hash) else cfg.owner_id


def revoke_session(cfg: BoardSettings, token: Optional[str]) -> None:
    """Revoke the session row now and drop it from this process's cache."""
    if not token or not _TOKEN_RE.match(token):
        return
    token_hash = _token_hash(token)
    _cache_revoke(token_hash)
    try:
        r = _rest(cfg, "PATCH", prefer="return=minimal",
                  params={"token_sha256": _hash_filter(token_hash), "revoked_at": "is.null"},
                  json={"revoked_at": datetime.now(timezone.utc).isoformat()})
    except SessionStoreError:
        _cache_unrevoke(token_hash)
        raise
    if r.status_code not in (200, 204):
        _cache_unrevoke(token_hash)
        raise SessionStoreError(f"revoke HTTP {r.status_code}")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, path="/",
                        secure=True, httponly=True, samesite="lax")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


# ─── known-device cookie ────────────────────────────────────────────────────

def _device_mac(cfg: BoardSettings, body: str) -> str:
    """Signs a known-device cookie with a key derived from the service-role key
    (server only), bound to the owner id: a new owner or key voids old cookies."""
    key = hmac.new(cfg.service_key.encode(), b"board known-device cookie v1", hashlib.sha256).digest()
    return hmac.new(key, f"{cfg.owner_id}|{body}".encode(), hashlib.sha256).hexdigest()


def new_device_cookie(cfg: BoardSettings) -> str:
    """A fresh known-device cookie value: random id, issue time, signature."""
    body = f"{secrets.token_urlsafe(16)}.{int(_wall())}"
    return f"{body}.{_device_mac(cfg, body)}"


def known_device(cfg: BoardSettings, value: Optional[str]) -> Optional[str]:
    """The device id when `value` is a known-device cookie this server gave a
    browser at an owner sign-in in the last DEVICE_DAYS, else None."""
    m = _DEVICE_RE.match(value or "")
    if not m:
        return None
    device, issued, mac = m.groups()
    if not hmac.compare_digest(mac, _device_mac(cfg, f"{device}.{issued}")):
        return None
    age = _wall() - int(issued)
    return device if -300 <= age <= DEVICE_DAYS * 86400 else None


def set_device_cookie(response: Response, value: str) -> None:
    response.set_cookie(DEVICE_COOKIE, value, max_age=DEVICE_DAYS * 86400, path="/",
                        secure=True, httponly=True, samesite="strict")


# ─── sign-in backoff (in memory: per device, per IP, per email) ─────────────

_attempts_lock = threading.Lock()   # every bucket: a check and its reservation are one step


class _Backoff:
    """Failed sign-ins per key. After `free` failures in the last hour, each
    further attempt waits 30 s after the last failure, doubling up to 15 min.
    A successful sign-in clears the key. An attempt counts as a failure from
    the moment it starts (see _reserve) until it ends some other way."""

    def __init__(self, free: int, memory: float = 3600.0, base: float = 30.0,
                 cap: float = 900.0, max_keys: int = 10_000):
        self.free, self.memory, self.base, self.cap, self.max_keys = free, memory, base, cap, max_keys
        self._fails: dict[str, deque] = {}

    # The underscore methods expect _attempts_lock held.
    def _recent(self, key: str, now: float) -> Optional[deque]:
        q = self._fails.get(key)
        while q and now - q[0] > self.memory:
            q.popleft()
        if not q:
            self._fails.pop(key, None)
            return None
        return q

    def _wait(self, key: str, now: float) -> float:
        q = self._recent(key, now)
        if q is None or len(q) < self.free:
            return 0.0
        delay = min(self.base * 2 ** min(len(q) - self.free, 16), self.cap)
        return max(0.0, q[-1] + delay - now)

    def _add(self, key: str, now: float) -> None:
        q = self._recent(key, now)
        if q is None:
            if len(self._fails) >= self.max_keys:
                for k in [k for k, d in self._fails.items() if not d or now - d[-1] > self.memory]:
                    del self._fails[k]
                if len(self._fails) >= self.max_keys:
                    self._fails.clear()
            q = self._fails[key] = deque(maxlen=64)
        q.append(now)

    def _drop(self, key: str, stamp: float) -> None:
        q = self._fails.get(key)
        if q is not None:
            try:
                q.remove(stamp)
            except ValueError:
                pass
            if not q:
                del self._fails[key]

    def wait(self, key: str) -> float:
        with _attempts_lock:
            return self._wait(key, _now())

    def fail(self, key: str) -> None:
        with _attempts_lock:
            self._add(key, _now())

    def clear(self, key: str) -> None:
        with _attempts_lock:
            self._fails.pop(key, None)

    def reset(self) -> None:
        with _attempts_lock:
            self._fails.clear()


# A browser without a known-device cookie: 5 free failures per client address
# and 10 per email. Both buckets are shared with other people (anyone can type
# the owner's email, and a client address is only as exact as the proxy headers),
# so a known device skips them and has a bucket of its own: 5 free failures.
_ip_backoff = _Backoff(free=5)
_email_backoff = _Backoff(free=10)
_device_backoff = _Backoff(free=5)


def _reserve(buckets: list) -> tuple[float, float]:
    """Check every bucket and, when none asks to wait, count this attempt as a
    failure in each: one step, so parallel attempts cannot all pass the check.
    Returns (seconds to wait, this attempt's stamp)."""
    now = _now()
    with _attempts_lock:
        wait = max(b._wait(key, now) for b, key in buckets)
        if wait <= 0:
            for b, key in buckets:
                b._add(key, now)
    return wait, now


def _release(buckets: list, stamp: float) -> None:
    """The attempt checked no password, or the service failed: uncount it."""
    with _attempts_lock:
        for b, key in buckets:
            b._drop(key, stamp)


def client_ip(request: Request) -> str:
    """Cloudflare's CF-Connecting-IP, else the first X-Forwarded-For hop (as the
    API rate limiter in core/api.py reads it), else the socket peer. It keys a
    slowdown only; the owner's known device does not depend on it."""
    ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if not ip:
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return ip[:64] or "unknown"


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def sign_in(request: Request, email: str, password: str) -> tuple[str, str]:
    """Check the password once with Supabase Auth and start a session for the
    owner. Returns the new session token and a fresh known-device cookie value;
    raises SignInError otherwise."""
    cfg = board_settings()
    if cfg is None:
        raise SignInError(503, "Sign-in is not configured on the server.")
    if not same_origin(request):
        raise SignInError(403, "Sign in from this site's sign-in page.")
    email = (email or "").strip()
    device = known_device(cfg, request.cookies.get(DEVICE_COOKIE))
    if device:
        buckets = [(_device_backoff, "device:" + device)]
    else:
        buckets = [(_ip_backoff, "ip:" + client_ip(request)), (_email_backoff, "email:" + email.lower())]
    wait, stamp = _reserve(buckets)
    if wait > 0:
        log.warning("board sign-in: backing off %s%s (%ds)", _mask(email),
                    " on a known device" if device else "", math.ceil(wait))
        raise SignInError(429, "Too many failed attempts. Try again later.", retry_after=math.ceil(wait))
    try:
        if not email or not password:
            raise SignInError(401, "Wrong email or password.")
        user_id = password_grant(cfg, email, password)
    except BaseException:
        _release(buckets, stamp)
        raise
    if user_id != cfg.owner_id:      # the attempt stays counted as a failure
        if user_id is None:
            log.info("board sign-in: wrong email or password for %s", _mask(email))
            raise SignInError(401, "Wrong email or password.")
        log.warning("board sign-in: refused a user who is not the board owner (%s)", _mask(email))
        raise SignInError(403, "This account cannot open the board.")
    try:
        token = create_session(cfg, user_id, request.headers.get("user-agent", ""))
    except SessionStoreError:
        _release(buckets, stamp)
        raise SignInError(502, "Could not start a session. Try again shortly.") from None
    for b, key in buckets:
        b.clear(key)
    log.info("board sign-in: owner signed in%s", " on a known device" if device else "")
    return token, new_device_cookie(cfg)


def safe_next(value: Optional[str]) -> str:
    """Where to go after sign-in: a relative path on this site, else the board."""
    v = (value or "").strip()
    # "/x" can carry no scheme or host; "//host" and "/\host" can, in browsers.
    if (not v.startswith("/") or v.startswith("//") or "\\" in v or len(v) > 2048
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in v)):
        return DEFAULT_NEXT
    return v


# ─── same-origin checks ─────────────────────────────────────────────────────

def _origin_tuple(value: str) -> Optional[tuple[str, str]]:
    """(scheme, host[:port]) of an origin or URL, lower case, default port dropped."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host or "@" in parts.netloc:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port and port != {"http": 80, "https": 443}[scheme]:
        host = f"{host}:{port}"
    return scheme, host


def same_origin(request: Request) -> bool:
    """True when the request's Origin (or, without one, its Referer) is this app's
    own origin: the host the browser asked for (Host), over https, or over plain
    http only when this request itself came in over http (local runs, tests)."""
    host = request.headers.get("host", "")
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http")
    own = _origin_tuple(f"{proto.split(',')[0].strip()}://{host}") if host else None
    origin = request.headers.get("origin")
    if origin is None:
        origin = request.headers.get("referer")
    if own is None or not origin or origin.strip() == "null":
        return False
    theirs = _origin_tuple(origin)
    return theirs is not None and theirs[1] == own[1] and theirs[0] in ("https", own[0])


def _cookie_use_allowed(request: Request) -> bool:
    """A request authenticated by the session cookie must come from this site."""
    if request.method.upper() in _UNSAFE_METHODS:
        return same_origin(request)
    if request.headers.get("origin") is not None and not same_origin(request):
        return False
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    return site in ("", "same-origin", "none")


# ─── gates ──────────────────────────────────────────────────────────────────

def api_cookie_status(request: Request) -> str:
    """The board cookie on an API request: 'ok', 'missing', 'invalid',
    'forbidden' (signed in, but not this site's own page), 'unconfigured' or
    'unavailable' (owner_sessions unreadable)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return "missing"
    cfg = board_settings()
    if cfg is None:
        return "unconfigured"
    try:
        if session_user(cfg, token) is None:
            return "invalid"
    except SessionStoreError as e:
        log.warning("board session check failed: %s", e)
        return "unavailable"
    return "ok" if _cookie_use_allowed(request) else "forbidden"


def require_owner(request: Request) -> str:
    """Dependency on every /api/board/* route. A plain def, so FastAPI runs the
    session read in its threadpool. Returns the owner's user id."""
    cfg = board_settings()
    if cfg is None:
        raise HTTPException(503, "Board sign-in is not configured")
    status = api_cookie_status(request)
    if status == "ok":
        return cfg.owner_id
    if status == "forbidden":
        raise HTTPException(403, "The board session works only on this site's own pages")
    if status == "unavailable":
        raise HTTPException(503, "Session check unavailable")
    raise HTTPException(401, "Not signed in")


def owner_session_allows(request: Request) -> bool:
    """For an admin API dependency that takes X-API-Key: True when a signed-in
    owner's own page makes this request; 403 or 503 when the cookie cannot be
    used; False when there is no usable session (the caller answers 401)."""
    status = api_cookie_status(request)
    if status == "forbidden":
        raise HTTPException(403, "The board session works only on this site's own pages")
    if status == "unavailable":
        raise HTTPException(503, "Session check unavailable")
    return status == "ok"


async def api_cookie_denial(request: Request) -> Optional[Response]:
    """For api_key_middleware when no valid X-API-Key came: None when a signed-in
    owner's own page makes this request, else the response to send instead."""
    if SESSION_COOKIE in request.cookies:
        status = await run_in_threadpool(api_cookie_status, request)
    else:
        status = "missing"
    if status == "ok":
        return None
    if status == "forbidden":
        return JSONResponse({"error": "Forbidden",
                             "hint": "The board session works only on this site's own pages"},
                            status_code=403)
    if status == "unavailable":
        return JSONResponse({"error": "Session check unavailable"}, status_code=503)
    return JSONResponse({"error": "Unauthorized", "hint": "Set X-API-Key header"}, status_code=401)


def _route_path(scope) -> str:
    """The path the router matches (the same rule as Starlette's get_route_path)."""
    path, root = scope.get("path", ""), scope.get("root_path", "")
    if root and path.startswith(root) and path[len(root):len(root) + 1] == "/":
        return path[len(root):]
    return path


def app_routes(app) -> list:
    """Every route the app serves, routers included. Newer FastAPI keeps an
    included router as one nested entry; iter_route_contexts flattens it."""
    routes = list(getattr(getattr(app, "router", None), "routes", None) or [])
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:   # older FastAPI copies router routes into app.routes
        return routes
    return list(iter_route_contexts(routes))


def _is_page_request(request: Request) -> bool:
    """GET or HEAD of a route that renders HTML, or of a path no route serves."""
    if request.method.upper() not in ("GET", "HEAD"):
        return False
    path = _route_path(request.scope)
    for route in app_routes(request.scope.get("app")):
        regex = getattr(route, "path_regex", None)
        if regex is not None and regex.match(path):
            rc = getattr(route, "response_class", None)
            rc = getattr(rc, "value", rc)     # FastAPI's DefaultPlaceholder
            return rc is None or (isinstance(rc, type) and issubclass(rc, HTMLResponse))
    return True


async def _admin_denial(request: Request) -> Optional[Response]:
    cfg = board_settings()
    if cfg is None:
        return PlainTextResponse("Board sign-in is not configured.", status_code=503, headers=_NO_STORE)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            if await run_in_threadpool(session_user, cfg, token):
                if request.method.upper() in _UNSAFE_METHODS and not same_origin(request):
                    return JSONResponse({"error": "Forbidden",
                                         "hint": "The board session works only on this site's own pages"},
                                        status_code=403, headers=_NO_STORE)
                return None
        except SessionStoreError as e:
            log.warning("board session check failed: %s", e)
            return PlainTextResponse("Session check unavailable. Try again shortly.",
                                     status_code=503, headers=_NO_STORE)
    if _is_page_request(request):
        query = request.scope.get("query_string", b"").decode("latin-1")
        target = request.scope.get("path", "/") + (f"?{query}" if query else "")
        response: Response = RedirectResponse(f"{LOGIN_PATH}?next={quote(target, safe='')}",
                                              status_code=302, headers=_NO_STORE)
    else:
        response = JSONResponse({"error": "Unauthorized", "hint": f"Sign in at {LOGIN_PATH}"},
                                status_code=401, headers=_NO_STORE)
    if token:
        clear_session_cookie(response)
    return response


class AdminPageGate:
    """ASGI middleware: every path that starts with /admin needs a signed-in
    owner session, whichever route, router or mount serves it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and _route_path(scope).startswith("/admin"):
            denial = await _admin_denial(Request(scope))
            if denial is not None:
                await denial(scope, receive, send)
                return
        await self.app(scope, receive, send)
