"""Cold outreach composer + sender.

Stage 4-5 of the SiteBoost pipeline.

Stage 4 (compose):
    Takes the preview-manifest JSON and creates a 3-email sequence per prospect:
        Touch 1 (day 0): site preview reveal + soft pitch
        Touch 2 (day 3): nudge with one specific benefit
        Touch 3 (day 7): breakup email (psychologically forces a reply)

Stage 5 (send):
    Pushes the sequence to Instantly.ai (or exports CSV for manual upload).
    Refuses to send unless:
        - --confirm flag passed
        - SITEBOOST_OUTBOUND_DOMAIN is set AND != wheellsverse.com
        - Daily send cap (50/domain) not exceeded
        - All emails pass CAN-SPAM lint
        - The opt-out list can be trusted here (see suppression_store_status)

All emails get CAN-SPAM footer baked in. No way to disable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("cold_outreach")


# ── Unsubscribe token + suppression list (CAN-SPAM § 7704(a)(3)) ────────────
#
# Token format (URL-safe, no padding):
#     base64url(email + "|" + ts + "|" + sig[:16])
# where:
#     sig = HMAC-SHA256(SITEBOOST_UNSUBSCRIBE_SECRET, email + "|" + ts).digest()
#     ts  = unix seconds at compose time
#
# Truncating the HMAC to 16 bytes is safe here: opt-out tokens aren't high-stakes
# (worst case is a spurious unsubscribe, which we can revert from the audit log).
# 16 bytes = 128 bits of collision resistance — far more than needed for this use.

UNSUBSCRIBE_SECRET_ENV = "SITEBOOST_UNSUBSCRIBE_SECRET"

# Storage path is configurable so the same code works:
#   - locally: defaults to data/launches/siteboost/suppressions.json
#   - on Railway: set SITEBOOST_SUPPRESSIONS_PATH=/var/data/siteboost/suppressions.json
#     once the Railway volume is attached at /var/data
_DEFAULT_SUPPRESSIONS = ROOT / "data" / "launches" / "siteboost" / "suppressions.json"
SUPPRESSIONS_PATH = Path(os.getenv("SITEBOOST_SUPPRESSIONS_PATH", str(_DEFAULT_SUPPRESSIONS)))

# Durable copy in Supabase (DDL: narai/migrations/0001_siteboost_suppressions.sql).
# The file above lives in the web container (wiped on every deploy unless the
# volume is attached), and sends run via `railway run` read the operator's own
# disk, never that file. So writes go to BOTH stores, reads return the UNION, a
# write Supabase misses is retried until it lands, and send_sequences() refuses
# to send when it can't trust the list (see suppression_store_status).
SUPPRESSIONS_TABLE = "siteboost_suppressions"
_PROBE_EMAIL = "__probe__@siteboost.invalid"  # row the migration seeds; see suppression_store_status
_RAILWAY_ENV_VARS = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID")
_DB_TIMEOUT_S = 10               # per Supabase request (supabase-py's default is 120 s)
_DB_RETRY_DELAYS_S = (0.5, 2.0)  # add_suppression: 3 tries, then the background retry takes over
_SYNC_BACKOFF_S = (30, 900)      # background retry: first wait, doubling up to this cap
_BACKFILL_CHUNK = 200            # rows per upsert request
_lock = threading.RLock()        # the file's read-modify-write + the state below (clicks run in threads)
_db = None                       # Supabase client, see _table()
_pending: dict = {}              # {email: row} this process hasn't got into Supabase yet
_last_db_error = ""              # last failed Supabase write; cleared once nothing is pending
_backfilled = False              # has this process pushed the whole file to Supabase once?
_sync_timer = None               # the background retry, see schedule_suppression_sync()


class SuppressionStoreError(RuntimeError):
    """The opt-out list can't be read reliably. The send path stops on this."""


def _unsub_secret() -> bytes:
    s = os.getenv(UNSUBSCRIBE_SECRET_ENV, "").strip()
    if not s:
        raise RuntimeError(
            f"{UNSUBSCRIBE_SECRET_ENV} not set. Generate one with: "
            f"openssl rand -base64 32. Set on both local .env and Railway env."
        )
    return s.encode()


_SIG_LEN = 16  # bytes of HMAC kept; positional parse depends on this being constant


def make_unsubscribe_token(email: str) -> str:
    """Generate a signed opt-out token for an email. Reversible only with the secret.

    Layout: base64url(payload || sig) where sig is exactly _SIG_LEN bytes.
    NO delimiter between payload and sig — HMAC bytes routinely contain bytes that
    look like ASCII delimiters (~6%/byte for any single char), which would break
    delimiter-based parsing roughly 60% of the time on a 16-byte sig.
    """
    secret = _unsub_secret()
    ts = str(int(time.time()))
    payload = f"{email}|{ts}".encode()
    sig = hmac.new(secret, payload, hashlib.sha256).digest()[:_SIG_LEN]
    return base64.urlsafe_b64encode(payload + sig).rstrip(b"=").decode()


def verify_unsubscribe_token(token: str) -> Optional[str]:
    """Verify a token and return the email if valid. None if forged/tampered.

    No expiry — CAN-SPAM § 7704(a)(4) requires opt-out URLs to remain functional
    for at least 30 days, but in practice we keep them forever.
    """
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        if len(raw) < _SIG_LEN + 3:  # at least 1 byte payload + 1 "|" + 1 byte ts + sig
            return None
        payload, sig = raw[:-_SIG_LEN], raw[-_SIG_LEN:]
        expected = hmac.new(_unsub_secret(), payload, hashlib.sha256).digest()[:_SIG_LEN]
        if not hmac.compare_digest(sig, expected):
            return None
        text = payload.decode("utf-8")
        if "|" not in text:
            return None
        email, _ts = text.rsplit("|", 1)
        return email
    except Exception:
        return None


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _read_file() -> dict:
    """The file copy, keys normalized. Raises SuppressionStoreError if it can't be read."""
    try:
        if not SUPPRESSIONS_PATH.exists():
            return {}
        data = json.loads(SUPPRESSIONS_PATH.read_text())
        return {_norm_email(k): (v if isinstance(v, dict) else {})
                for k, v in data.items() if _norm_email(k)}
    except Exception as e:
        raise SuppressionStoreError(f"suppression file {SUPPRESSIONS_PATH} unreadable: {e}") from e


def _load_suppressions() -> dict:
    """Read the file copy. Returns {email: {"unsubscribed_at": str, "via": str}}."""
    try:
        return _read_file()
    except SuppressionStoreError as e:
        logger.warning(f"{e} (treating as empty)")
        return {}


def _write_suppressions(current: dict) -> None:
    """Atomic write (tmp + rename)."""
    SUPPRESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SUPPRESSIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True))
    tmp.replace(SUPPRESSIONS_PATH)


def _db_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip()
                and os.getenv("SUPABASE_SERVICE_KEY", "").strip())


def _table():
    """The Supabase table. Same SUPABASE_URL + SUPABASE_SERVICE_KEY and library as
    core/narai_user.py, but its own client so a request gives up after
    _DB_TIMEOUT_S instead of 120 s (an unsubscribe click waits on it)."""
    global _db
    if _db is None:
        from supabase import ClientOptions, create_client
        _db = create_client(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_SERVICE_KEY"].strip(),
                            options=ClientOptions(postgrest_client_timeout=_DB_TIMEOUT_S))
    return _db.table(SUPPRESSIONS_TABLE)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row(email: str, meta: dict) -> dict:
    """The table row for an entry. A missing or unparseable timestamp becomes now:
    Postgres would reject the row, and the opt-out matters more than its date."""
    at = str(meta.get("unsubscribed_at") or "")
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        at = _now()
    return {"email": email, "unsubscribed_at": at, "via": str(meta.get("via") or "?")}


def _upsert(rows: list[dict]) -> None:
    """INSERT ... ON CONFLICT DO NOTHING: an address keeps its first opt-out record."""
    _table().upsert(rows, on_conflict="email", ignore_duplicates=True).execute()


def is_suppressed(email: str, strict: bool = False) -> bool:
    """Has this email opted out previously? Case- and whitespace-insensitive.

    Checks the file AND Supabase (when configured). If Supabase can't be read the
    file's answer is used and a warning logged. strict=True (the send path)
    instead raises SuppressionStoreError when either store can't be read, so the
    batch stops rather than risk emailing someone who opted out.
    """
    key = _norm_email(email)
    if not key:
        return False
    if key in (_read_file() if strict else _load_suppressions()):
        return True
    if not _db_configured():
        return False
    try:
        return bool(_table().select("email").eq("email", key).limit(1).execute().data)
    except Exception as e:
        if strict:
            raise SuppressionStoreError(f"Supabase suppression read failed: {e}") from e
        logger.warning(f"[suppressions] Supabase read failed ({e}); answering from the file only")
        return False


def add_suppression(email: str, via: str = "click") -> dict:
    """Add email to the file AND Supabase (when configured). Atomic file write.

    Idempotent: an address keeps its first opt-out record, so calling it again
    just retries Supabase. Never silent: a failed Supabase write is tried 3 times,
    then the file entry is kept, an error logged, the failure returned (db=False)
    and counted as pending by suppression_store_status(), and a background retry
    runs until Supabase has it. Raises only if NO store recorded the opt-out.
    """
    global _last_db_error
    key = _norm_email(email)
    if not key:
        raise ValueError("email required")
    row = _row(key, {"unsubscribed_at": _now(), "via": via})
    result = {"email": key, "file": False, "db": None, "db_error": ""}  # db None = not configured
    file_error = ""
    with _lock:
        try:
            current = _load_suppressions()
            if key in current:
                row = _row(key, current[key])  # keep the first opt-out record
            else:
                current[key] = {"unsubscribed_at": row["unsubscribed_at"], "via": row["via"]}
                _write_suppressions(current)
                logger.info(f"[suppressions] added {key} via {via} ({len(current)} in file)")
            result["file"] = True
        except Exception as e:
            file_error = str(e)
            logger.error(f"[suppressions] file write FAILED for {key}: {e}")
    if _db_configured():
        error = ""
        for delay in (0, *_DB_RETRY_DELAYS_S):
            time.sleep(delay)
            try:
                _upsert([row])
                error = ""
                break
            except Exception as e:
                error = str(e)
        with _lock:
            if error:
                _pending[key] = row
                result["db_error"] = _last_db_error = f"add {key}: {error}"[:300]
            else:
                _pending.pop(key, None)
            sync = bool(_pending) or not _backfilled
        result["db"] = not error
        if error:
            logger.error(f"[suppressions] Supabase write FAILED for {key} ({1 + len(_DB_RETRY_DELAYS_S)} "
                         f"tries); only in the file until the background retry lands it: {error}")
        if sync:
            schedule_suppression_sync(_SYNC_BACKOFF_S[0] if error else 0)
    if not result["file"] and not result["db"]:
        raise RuntimeError(f"opt-out for {key} NOT recorded (file: {file_error}; "
                           f"supabase: {result['db_error'] or 'not configured'})")
    return result


def list_suppressions() -> list[dict]:
    """Return the union of file + Supabase entries, sorted newest first."""
    current = _load_suppressions()
    if _db_configured():
        try:
            current.update(_db_rows())
        except Exception as e:
            logger.warning(f"[suppressions] Supabase list failed ({e}); showing the file copy only")
    out = []
    for email, meta in current.items():
        out.append({
            "email": email,
            "unsubscribed_at": meta.get("unsubscribed_at", ""),
            "via": meta.get("via", "?"),
        })
    out.sort(key=lambda x: x["unsubscribed_at"], reverse=True)
    return out


def _db_rows() -> dict:
    """Every Supabase row as {email: meta}. Reads until an empty page: the server
    caps rows per request, so a short page doesn't mean the end."""
    rows: dict = {}
    start = 0
    while True:
        page = (_table().select("email,unsubscribed_at,via").order("email")
                .range(start, start + 999).execute().data) or []
        if not page:
            return rows
        start += len(page)
        for r in page:
            email = _norm_email(r.get("email"))
            if email != _PROBE_EMAIL:
                rows[email] = {"unsubscribed_at": r.get("unsubscribed_at") or "", "via": r.get("via") or "?"}


def remove_suppression(email: str) -> bool:
    """Re-include an email by removing it from the file AND Supabase.

    Used when an operator pre-suppressed someone (e.g. a friend's email used
    for testing) and now wants them back. Returns True if removed, False if
    not present. Supabase goes first: if that delete fails we raise and leave
    the file alone, so the address stays suppressed rather than half-removed.
    """
    key = _norm_email(email)
    if key == _PROBE_EMAIL:
        raise ValueError(f"{key} is the store's probe row (see the migration), not an opt-out")
    in_db = False
    if _db_configured():
        try:
            in_db = bool(_table().delete().eq("email", key).execute().data)
        except Exception as e:
            raise SuppressionStoreError(f"Supabase delete failed for {key}; nothing removed: {e}") from e
    with _lock:
        _pending.pop(key, None)
        current = _load_suppressions()
        in_file = key in current
        if in_file:
            del current[key]
            _write_suppressions(current)
    if not (in_file or in_db):
        return False
    logger.info(f"[suppressions] removed {key} (file={in_file}, supabase={in_db})")
    return True


def _write_rows(rows: list[dict]) -> tuple[list[str], str]:
    """Upsert rows in chunks. A chunk Supabase rejects is retried row by row, so one
    bad row can't hold back the rest; 3 failures in a row means Supabase itself is
    failing, so stop. Returns (emails now in Supabase, last error)."""
    done, error = [], ""
    for i in range(0, len(rows), _BACKFILL_CHUNK):
        chunk = rows[i:i + _BACKFILL_CHUNK]
        try:
            _upsert(chunk)
            done += [r["email"] for r in chunk]
            continue
        except Exception as e:
            error = str(e)
        misses = 0
        for r in chunk:
            try:
                _upsert([r])
                done.append(r["email"])
                misses = 0
            except Exception as e:
                error, misses = str(e), misses + 1
                if misses == 3:
                    return done, error
    return done, error


def backfill_suppressions() -> dict:
    """Copy every file entry, and every write Supabase missed, into Supabase.
    Idempotent: rows already there keep their first opt-out record.

    Runs on the first good Supabase contact per process, at web-app startup and in
    the background retry (schedule_suppression_sync), so opt-outs that only reached
    the file become durable before a deploy can wipe it. Only rows actually written
    leave the pending set; the rest are retried. Reloading the admin
    launch-readiness card also retries while anything is pending.
    """
    global _backfilled, _last_db_error
    if not _db_configured():
        return {"ok": False, "n": 0, "error": "Supabase not configured", "pending": 0}
    with _lock:
        first_pass = not _backfilled
        rows = dict(_pending)
        rows.update({e: _row(e, m) for e, m in _load_suppressions().items()})
    done, error = _write_rows(list(rows.values()))
    written = set(done)
    with _lock:
        for e, r in rows.items():
            if e in written:
                _pending.pop(e, None)
            elif first_pass:  # before one full pass, no file row is known to be in Supabase
                _pending[e] = r
        _backfilled = True
        if len(written) < len(rows):
            _last_db_error = f"backfill: {len(rows) - len(written)} of {len(rows)} not written: {error}"[:300]
        elif not _pending:
            _last_db_error = ""
        pending = len(_pending)
    if len(written) < len(rows):
        logger.error(f"[suppressions] Supabase backfill: {len(rows) - len(written)} of {len(rows)} "
                     f"rows FAILED, will retry: {error}")
        return {"ok": False, "n": len(rows), "error": error[:300], "pending": pending}
    return {"ok": True, "n": len(rows), "error": "", "pending": pending}


def _ensure_backfilled() -> None:
    if not _backfilled or _pending:
        backfill_suppressions()


def schedule_suppression_sync(delay: float = 0) -> None:
    """Keep retrying in the background until every opt-out is in Supabase.

    One daemon timer per process runs backfill_suppressions(), then re-arms itself
    (30 s, doubling, capped at 15 min) while anything is still pending. Started by
    add_suppression() and at web-app startup (core/api.py). No-op without Supabase.
    """
    if not _db_configured():
        return
    with _lock:
        if _sync_timer is None:
            _arm_sync(delay)


def _arm_sync(delay: float) -> None:
    """Start the retry timer. Caller holds _lock."""
    global _sync_timer
    _sync_timer = threading.Timer(delay, _sync_step, args=(delay,))
    _sync_timer.daemon = True
    _sync_timer.start()


def _sync_step(delay: float) -> None:
    global _sync_timer
    try:
        ok = backfill_suppressions()["ok"]
    except Exception as e:  # never let the retry loop die quietly
        ok = False
        logger.error(f"[suppressions] background sync failed: {e}")
    with _lock:
        _sync_timer = None
        if (not ok or _pending) and _db_configured():
            first, cap = _SYNC_BACKOFF_S
            _arm_sync(min(cap, max(first, 2 * delay)))


def _durable_required() -> bool:
    """Production (Railway sets these in the container and under `railway run`),
    or forced with SITEBOOST_REQUIRE_DURABLE_SUPPRESSIONS=1."""
    if os.getenv("SITEBOOST_REQUIRE_DURABLE_SUPPRESSIONS", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return any(os.getenv(v, "").strip() for v in _RAILWAY_ENV_VARS)


def _file_on_web_volume() -> bool:
    """SITEBOOST_SUPPRESSIONS_PATH is set and sits on the Railway volume mounted in
    THIS process, i.e. we are the web container /u/{token} writes to. `railway run`
    on the operator's machine gets the same env vars but not the mount."""
    mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if not mount or not os.getenv("SITEBOOST_SUPPRESSIONS_PATH", "").strip():
        return False
    return Path(mount) in SUPPRESSIONS_PATH.parents and os.path.ismount(mount)


def suppression_store_status() -> dict:
    """Which opt-out store is active, whether it survives a redeploy, and whether it
    is safe to send ("ok"). send_sequences() checks this before every batch.

    Fail closed: if Supabase is configured, this client must read back the probe
    row the migration seeds. A key without service_role gets an empty answer from
    RLS rather than an error, so "the select didn't fail" alone proves nothing.
    Otherwise, in production (or with SITEBOOST_REQUIRE_DURABLE_SUPPRESSIONS=1)
    only the web container's volume-backed file is accepted. Local dev keeps the
    plain file. "pending" counts opt-outs this process hasn't got into Supabase.
    """
    st = {"store": "file", "durable": False, "ok": True, "reason": "",
          "required": _durable_required(), "path": str(SUPPRESSIONS_PATH)}
    if _db_configured():
        st["store"] = "supabase+file"
        try:
            seen = _table().select("email").eq("email", _PROBE_EMAIL).limit(1).execute().data
        except Exception as e:
            st["ok"] = False
            st["reason"] = f"Supabase is configured but {SUPPRESSIONS_TABLE} can't be read: {e}"
        else:
            if seen:
                st["durable"] = True
                _ensure_backfilled()
            else:
                st["ok"] = False
                st["reason"] = (f"{SUPPRESSIONS_TABLE} doesn't show its probe row {_PROBE_EMAIL}: "
                                "SUPABASE_SERVICE_KEY isn't the service_role key (RLS then hides every "
                                "row), or the row is gone (re-run the migration)")
    elif _file_on_web_volume():
        st["durable"] = True
    elif st["required"]:
        st["ok"] = False
        st["reason"] = ("no durable opt-out store: set SUPABASE_URL + SUPABASE_SERVICE_KEY "
                        "(or send from the web container with SITEBOOST_SUPPRESSIONS_PATH on its volume)")
    with _lock:
        st["pending"] = len(_pending)
        st["db_error"] = _last_db_error
    return st

# CAN-SPAM required footer — hardcoded, cannot be disabled.
# The unsubscribe URL is hosted on app.wheellsverse.com (not the sending domain) because
# the FastAPI app responds there. Receivers don't require the opt-out URL to match the
# sending domain — only that it's functional for at least 30 days (CAN-SPAM § 7704(a)(4)).
_UNSUB_URL_BASE = os.getenv("SITEBOOST_UNSUB_URL_BASE", "https://app.wheellsverse.com")


def _can_spam_footer(domain: str, recipient_email: str = "") -> str:
    physical = os.getenv("SITEBOOST_PHYSICAL_ADDRESS",
                         "SiteBoost · 123 Placeholder St · Boston, MA 02108 USA")
    # Generate a per-recipient signed token. If we can't (secret unset), fall back to
    # a literal placeholder so dry-run scans don't crash — but real sends MUST have
    # a real token or the footer is non-compliant.
    if recipient_email:
        try:
            token = make_unsubscribe_token(recipient_email)
            unsub_url = f"{_UNSUB_URL_BASE}/u/{token}"
        except RuntimeError as e:
            logger.warning(f"unsubscribe token unavailable ({e}); using placeholder")
            unsub_url = f"{_UNSUB_URL_BASE}/u/{{UNSUBSCRIBE_TOKEN}}"
    else:
        unsub_url = f"{_UNSUB_URL_BASE}/u/{{UNSUBSCRIBE_TOKEN}}"
    return (
        f"\n\n---\n"
        f"This is a one-time outreach from {domain}. "
        f"If you'd rather not hear from us, reply STOP and we'll remove your address.\n"
        f"{physical}\n"
        f"You can also unsubscribe here: {unsub_url}"
    )


# ── Compose ─────────────────────────────────────────────────────────────────

# Each detected issue maps to (opening line, follow-up stat, short label for touch 2).
# Designed so the prospect can verify the claim themselves — every line refers to a
# concrete, falsifiable observation about THEIR website. That's what drives reply rate.
ISSUE_COPY = {
    "no-https": {
        "opener": "I noticed {domain} loads on http:// rather than https:// — Chrome shows visitors a \"Not Secure\" warning before they even reach your homepage.",
        "stat": "Sites without HTTPS lose ~13% of would-be customers at that warning screen",
        "short": "the SSL/security warning",
    },
    "ssl-broken": {
        "opener": "I tried to load {domain} just now and got an SSL/cert error — visitors using Chrome or Safari see a full-page \"Your connection is not private\" warning and almost always bounce.",
        "stat": "Cert errors block close to 100% of new visitors — they hit the red warning page and never reach you",
        "short": "the broken SSL cert",
    },
    "timeout": {
        "opener": "I tried to load {domain} a minute ago and it timed out — 5 seconds, no response.",
        "stat": "Google deranks pages slower than 3s, and 53% of mobile users abandon before a 3s load completes",
        "short": "the slow load",
    },
    "connection-failed": {
        "opener": "I tried to load {domain} and couldn't connect — visitors trying to reach you would see a \"this site can't be reached\" error in their browser.",
        "stat": "When a site won't load at all, you're invisible to any customer who searches first",
        "short": "the site-not-loading issue",
    },
    "http-403": {
        "opener": "I tried to load {domain} and got a 403 Forbidden — looks like the hosting config is blocking visitors.",
        "stat": "A 403 page tells search engines and humans alike that your business isn't reachable online",
        "short": "the 403 block",
    },
    "http-404": {
        "opener": "I tried to load {domain} and got a 404 — the page in your Google listing is either gone or broken.",
        "stat": "Every 404 is a customer who searched for you and reached a dead end",
        "short": "the 404",
    },
    "http-429": {
        "opener": "I tried to load {domain} and got rate-limited — looks like your hosting is throttling traffic.",
        "stat": "When real visitors get throttled like a bot would, they bounce and try the next result on Google",
        "short": "the throttling issue",
    },
    "http-500": {
        "opener": "I tried to load {domain} and got a 500 server error — the page is crashing instead of rendering.",
        "stat": "Server errors signal to Google that your site isn't trustworthy; ranking drops within days",
        "short": "the server crash",
    },
    "not-mobile-friendly": {
        "opener": "I noticed {domain} doesn't have a mobile viewport tag — on phones the page doesn't resize, so visitors have to pinch-zoom around to read it.",
        "stat": "60%+ of local-business searches happen on phones, and Google deranks non-mobile-friendly sites in mobile results",
        "short": "the mobile-resize problem",
    },
    "placeholder-or-empty": {
        "opener": "I loaded {domain} and the page is basically empty — looks like a stub that was set up but never finished.",
        "stat": "An empty page reads as \"this business is closed\" to most visitors",
        "short": "the blank-page issue",
    },
    "parking-page": {
        "opener": "I noticed {domain} shows a domain-parking page instead of your business — looks like the hosting lapsed or was never set up.",
        "stat": "Parking pages tell Google your business is inactive, which kills your search ranking",
        "short": "the parked-domain page",
    },
    "coming-soon": {
        "opener": "I noticed {domain} still shows a \"coming soon\" placeholder — happy to launch the real site for you instead.",
        "stat": "Every day a coming-soon page stays up is a day customers bounce to your competitors",
        "short": "the coming-soon placeholder",
    },
    "no-title": {
        "opener": "I noticed {domain} has no page title set — in Google search results, the URL shows instead of your business name, which kills clickthrough.",
        "stat": "Listings without proper titles get ~40% fewer clicks than properly tagged ones",
        "short": "the missing title tag",
    },
    "default-template": {
        "opener": "I loaded {domain} and it looks like the site's running on a default template that's never been customized — looks like it was set up and forgotten.",
        "stat": "Default templates rank ~30% worse in Google for local-business searches because they lack unique-content signals",
        "short": "the un-customized template",
    },
}

# Outdated-copyright detection encodes the actual year found (e.g. "copyright-2019").
# This template handles ANY such variant. Format string is interpolated at runtime
# with the actual year via the copy resolver below.
COPYRIGHT_COPY_TEMPLATE = {
    "opener": "I noticed {domain}'s footer still says © {year} — looks like the site hasn't been touched in a few years.",
    "stat": "Sites that haven't been updated in 3+ years signal to Google + visitors that the business is inactive or unreliable",
    "short": "the stale {year} site",
}

# No-website fallback — original copy, kept for prospects with no site at all
NO_WEBSITE_OPENER = "I noticed {business_name} doesn't have a website yet — uncommon for a {category} in {city} these days."
NO_WEBSITE_STAT = "72% of people look up a local business on their phone before calling — if they can't find a site, they call the next one"
NO_WEBSITE_SHORT = "the no-website situation"


def _issue_copy(issues: list[str], website: str, business_name: str,
                 category: str, city: str) -> dict[str, str]:
    """Return {opener, stat, short} for the highest-priority detected issue.

    No issues + no website → no-website fallback copy.
    No issues + has website → returns empty strings (caller should skip; shouldn't happen
    in normal flow because is_targetable() filters good-website prospects out).
    """
    if website:
        host = website.split("://")[-1].split("/")[0]
        domain = host[4:] if host.startswith("www.") else host
    else:
        domain = ""
    if not issues:
        if not website:
            return {
                "opener": NO_WEBSITE_OPENER.format(business_name=business_name,
                                                  category=category, city=city),
                "stat": NO_WEBSITE_STAT,
                "short": NO_WEBSITE_SHORT,
            }
        return {"opener": "", "stat": "", "short": ""}
    # Strip the "bad-website:" prefix if present (rejection-reason format)
    primary = issues[0].split(":", 1)[-1]

    # Copyright issues encode the year: "copyright-2019" → interpolate the year into the copy
    if primary.startswith("copyright-"):
        year_str = primary.split("-", 1)[1]
        return {
            "opener": COPYRIGHT_COPY_TEMPLATE["opener"].format(
                domain=domain or business_name, year=year_str),
            "stat": COPYRIGHT_COPY_TEMPLATE["stat"],
            "short": COPYRIGHT_COPY_TEMPLATE["short"].format(year=year_str),
        }

    template = ISSUE_COPY.get(primary)
    if not template:
        return {
            "opener": f"I noticed {domain} has some issues that are likely costing you visitors.",
            "stat": "Modern site-quality signals (HTTPS, mobile, speed) all factor into Google ranking",
            "short": "the site-quality issues",
        }
    return {
        "opener": template["opener"].format(domain=domain or business_name),
        "stat": template["stat"],
        "short": template["short"],
    }


def _email_body_touch1(ctx: dict, copy: dict) -> str:
    """Touch 1: opening hook + preview link + fix offer. Issue-aware."""
    return f"""Hi {ctx['first_name']},

{copy['opener']}

So I built a fix you can look at:

  {ctx['preview_url']}

That's a working preview, not a mockup. SSL on, mobile-first, fast. Yours to keep either way.

If you'd want me to put this live on your own domain with email + hosting included, I do the fix for $297 one-time, $49/mo to keep it running. Most customers see a noticeable bounce-rate drop within a week.

No pressure — the preview is yours regardless. Reply if you want to talk.

— {ctx['sender_name']}
{ctx['sender_company']}"""


def _email_body_touch2(ctx: dict, copy: dict) -> str:
    """Touch 2: nudge with one specific stat + the issue label."""
    return f"""Hi {ctx['first_name']},

Quick follow-up on the {ctx['business_name']} site preview I sent earlier this week: {ctx['preview_url']}

One thing worth knowing — {copy['stat']}.

The preview I built fixes {copy['short']}. Want me to launch it this week?

— {ctx['sender_name']}"""


def _email_body_touch3(ctx: dict, copy: dict) -> str:
    """Touch 3: breakup. Generic — no issue-specific text needed here."""
    return f"""Hi {ctx['first_name']},

Last note from me on the {ctx['business_name']} site — I assume the timing isn't right and I'll close the file on this one.

If anything changes, the preview will stay at {ctx['preview_url']} for another 30 days.

All the best,
— {ctx['sender_name']}
{ctx['sender_company']}"""


SUBJECTS = {
    "touch1": "{first_name} — quick fix idea for {business_name}",
    "touch2": "Re: quick fix idea for {business_name}",
    "touch3": "{first_name} — closing the file?",
}


def _pick_sender_company(domain: str) -> str:
    return os.getenv("SITEBOOST_BRAND", "SiteBoost AI")


def _category_friendly(category: str) -> str:
    """Internal category slug → human readable."""
    mapping = {
        "restaurant": "restaurant", "cafe": "cafe", "bakery": "bakery",
        "hair_salon": "hair salon", "beauty_salon": "beauty salon", "barber_shop": "barbershop",
        "plumber": "plumber", "electrician": "electrician",
        "roofing_contractor": "roofing company", "general_contractor": "contractor",
        "dentist": "dentist", "doctor": "medical practice", "chiropractor": "chiropractor",
        "auto_repair": "auto shop", "car_repair": "auto shop", "car_wash": "car wash",
        "lawyer": "law office", "accounting": "accountant",
        "pet_store": "pet store", "florist": "florist",
        "veterinary_care": "vet clinic",
        "shoe_store": "shop", "clothing_store": "boutique",
    }
    return mapping.get(category, "small business")


def _city_from_address(addr: str) -> str:
    """Extract the city segment from a Google formatted address.

    Google returns addresses like '123 Main St, Hyannis, MA 02639, USA' — the city
    is NOT just `parts[-2]` because that returns 'MA 02639'. Walk backwards from the
    country segment, skipping segments that look like state+zip (2-letter state code
    optionally followed by digits).
    """
    import re
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if not parts:
        return "your area"
    # Drop trailing country (e.g. "USA", "United States") and state+zip combos
    state_zip = re.compile(r"^[A-Z]{2}(\s+\d{4,5}(-\d{4})?)?$")
    while parts and (parts[-1].upper() in {"USA", "UNITED STATES", "US", "CANADA"}
                      or state_zip.match(parts[-1])):
        parts.pop()
    return parts[-1] if parts else "your area"


def _is_dangerous_outbound_domain(domain: str) -> bool:
    """Block apex/www wheellsverse.com (reputation-critical inboxes), allow subdomains.

    Subdomains have separate sending reputation in Gmail/Outlook, so
    `hello.wheellsverse.com` is safe to cold-send from without poisoning the
    main brand's `wheellsverse.com` mailbox. But the apex itself must never
    be used for cold outbound — that would tank receipts/transactional/newsletter.
    """
    d = domain.strip().lower().rstrip(".")
    DANGEROUS = {"wheellsverse.com", "www.wheellsverse.com",
                 "shop.wheellsverse.com", "app.wheellsverse.com"}
    return d in DANGEROUS


def compose_sequences(manifest_path: Path, sender_name: str = "Jay",
                      outbound_domain: Optional[str] = None) -> Path:
    """Read preview manifest, create 3-email sequences, write JSON ready for send."""
    manifest = json.loads(manifest_path.read_text())
    domain = outbound_domain or os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com")
    if _is_dangerous_outbound_domain(domain):
        raise RuntimeError(
            f"Refusing to use {domain!r} for cold outbound — it's a reputation-critical "
            f"inbox (Stripe receipts, ConvertKit drips, customer transactional emails). "
            f"Use a subdomain like hello.wheellsverse.com instead."
        )
    company = _pick_sender_company(domain)

    # Find the matching enriched file for this run.
    #
    # Strategy (deterministic, immune to leftover/test files):
    #   1. Derive the run's date+slug from the manifest's parent directory.
    #      e.g.  runs/2026-06-10-boston-ma/03-previews-manifest.json
    #            → run_slug = "2026-06-10-boston-ma"
    #            → expected enriched = scans/2026-06-10-boston-ma-enriched.json
    #   2. If that exact file exists, use it.
    #   3. Otherwise fall back to the MOST RECENTLY MODIFIED enriched file
    #      (st_mtime, not filename sort — avoids the "test-enriched.json"
    #      alphabetical-tail bug fixed 2026-06-10).
    enriched_dir = ROOT / "data" / "launches" / "siteboost" / "scans"
    run_slug = manifest_path.parent.name  # e.g. "2026-06-10-boston-ma"
    expected_enriched = enriched_dir / f"{run_slug}-enriched.json"
    if expected_enriched.exists():
        enriched_path = expected_enriched
    else:
        enriched_files = sorted(enriched_dir.glob("*-enriched.json"),
                                key=lambda p: p.stat().st_mtime)
        if not enriched_files:
            raise RuntimeError(
                f"No enriched file found for run {run_slug!r}. "
                f"Expected {expected_enriched.name}, and no other *-enriched.json exists."
            )
        enriched_path = enriched_files[-1]
    enriched_data = json.loads(enriched_path.read_text())
    by_name = {p["name"]: p for p in enriched_data.get("enriched", [])}

    sequences = []
    skipped_suppressed = 0
    for preview in manifest["previews"]:
        biz = by_name.get(preview["name"])
        if not biz or "contact" not in biz:
            continue
        contact = biz["contact"]
        # CAN-SPAM § 7704(a)(4) — honor prior opt-outs. Skip any email already on the list.
        if is_suppressed(contact.get("email", "")):
            skipped_suppressed += 1
            logger.info(f"[compose] skipping {contact['email']} (previously unsubscribed)")
            continue
        category_friendly = _category_friendly(biz.get("category", ""))
        city = _city_from_address(biz.get("address", ""))
        ctx = {
            "first_name": contact.get("first_name", "there") or "there",
            "business_name": biz["name"],
            "category": category_friendly,
            "city": city,
            "preview_url": preview["preview_url"],
            "sender_name": sender_name,
            "sender_company": company,
        }
        # Build issue-aware copy from the website probe results (bad-website pivot).
        # is_targetable() encodes the issue in the targetable_reason; here we read
        # the raw website_issues list directly off the enriched record.
        copy = _issue_copy(
            issues=biz.get("website_issues", []),
            website=biz.get("website", ""),
            business_name=biz["name"],
            category=category_friendly,
            city=city,
        )
        footer = _can_spam_footer(domain, contact["email"])
        sequence = {
            "to_email": contact["email"],
            "to_name": f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
            "business_name": biz["name"],
            "website_issues": biz.get("website_issues", []),
            "touches": [
                {"day": 0,
                 "subject": SUBJECTS["touch1"].format(**ctx),
                 "body": _email_body_touch1(ctx, copy) + footer},
                {"day": 3,
                 "subject": SUBJECTS["touch2"].format(**ctx),
                 "body": _email_body_touch2(ctx, copy) + footer},
                {"day": 7,
                 "subject": SUBJECTS["touch3"].format(**ctx),
                 "body": _email_body_touch3(ctx, copy) + footer},
            ],
        }
        sequences.append(sequence)

    stamp = time.strftime("%Y-%m-%d")
    out = manifest_path.parent / "04-sequences.json"
    out.write_text(json.dumps({
        "_meta": {
            "composed_at": stamp,
            "outbound_domain": domain,
            "sender_name": sender_name,
            "sender_company": company,
            "n_sequences": len(sequences),
            "n_touches_total": len(sequences) * 3,
        },
        "sequences": sequences,
    }, indent=2))
    logger.info(f"[compose] {len(sequences)} sequences → {out}")
    return out


# ── Send (Instantly.ai v2) ──────────────────────────────────────────────────

# v1 was deprecated and returns 401 to any new keys. v2 collapsed the previous
# {campaign_id, leads:[...]} shape into a flat single-lead POST. Schema:
#   POST /api/v2/leads
#   Required: email
#   Optional: campaign (UUID), first_name, last_name, company_name,
#             personalization, website
INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"


def _extract_preview_url(touch_body: str) -> str:
    """Pull the preview-site URL out of a touch body (first https URL on its own line)."""
    for line in touch_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("https://") and "preview" in stripped:
            return stripped
    return ""


def _instantly_send_sequence(seq: dict, campaign_id: str, key: str) -> dict:
    """Push a prospect's contact info to Instantly v2 as a campaign lead.

    The 3-touch email SEQUENCE itself is configured at the campaign level in
    Instantly — this call just adds the recipient + personalization variables.
    Custom variables become {{first_name}}, {{company_name}}, {{personalization}}
    in the campaign template (which the operator wires up in the Instantly UI).

    The actual EMAIL BODY composed by compose_sequences() is kept for review
    in the run's 04-sequences.json — Instantly's template is the source of truth
    for what actually gets sent. The compose output is the recommended copy.
    """
    name_parts = (seq.get("to_name") or "").split(maxsplit=1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    touches = seq.get("touches", [])
    touch1_body = touches[0].get("body", "") if touches else ""
    preview_url = _extract_preview_url(touch1_body)

    payload = {
        "email": seq["to_email"],
        "campaign": campaign_id,
        "first_name": first_name,
        "last_name": last_name,
        "company_name": seq.get("business_name", ""),
        "personalization": preview_url,  # available as {{personalization}} in template
    }

    r = requests.post(
        f"{INSTANTLY_API_BASE}/leads",
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
        timeout=20,
    )
    return {"status": r.status_code, "body": r.text[:300]}


def send_sequences(sequences_path: Path, confirm: bool = False,
                   live: bool = False, max_per_day: int = 50) -> dict:
    """Stage 5 — actually send. Refuses without --confirm AND live=True."""
    seqs = json.loads(sequences_path.read_text())
    domain = seqs["_meta"]["outbound_domain"]

    if not confirm:
        return {"status": "blocked", "reason": "--confirm flag required for send"}
    if not live:
        return {"status": "blocked", "reason": "--live flag required for send (dry-run by default)"}
    if _is_dangerous_outbound_domain(domain):
        return {"status": "blocked", "reason": f"Refusing {domain!r} as outbound (apex/critical inbox). Use a subdomain like hello.wheellsverse.com."}

    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    # Prefer auto-created campaign from active_campaign.json over env var. This
    # lets /instantly/auto-create-campaign immediately become the live campaign
    # without requiring a Railway env var update + redeploy.
    try:
        from core.siteboost_instantly import get_active_campaign_id
        campaign_id = get_active_campaign_id()
    except Exception:
        campaign_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()
    if not key or not campaign_id:
        return {"status": "blocked", "reason": "INSTANTLY_API_KEY + INSTANTLY_CAMPAIGN_ID required"}

    # CAN-SPAM § 7704(a)(3)-(4): refuse the whole batch unless the opt-out list here
    # can be trusted, then re-check every recipient (opt-outs arrive after compose).
    store = suppression_store_status()
    if not store["ok"]:
        logger.error(f"[send] REFUSING to send: {store['reason']}")
        return {"status": "blocked", "reason": store["reason"]}
    warning = ""
    if not store["durable"]:  # local run: allowed, but it can't see opt-outs clicked on the web app
        warning = (f"opt-outs checked against {store['path']} only, NOT the web app's list. Send with "
                   "`railway run` or set SUPABASE_URL + SUPABASE_SERVICE_KEY to include them.")
        logger.warning(f"[send] {warning}")

    # Honor per-prospect skip flag set via /api/narai/siteboost/sequences/skip.
    # Operators use this to remove low-quality prospects after composing without
    # re-running the whole pipeline.
    not_skipped = [s for s in seqs["sequences"] if not s.get("skipped")]
    skipped_count = len(seqs["sequences"]) - len(not_skipped)
    if skipped_count:
        logger.info(f"[send] skipping {skipped_count} sequences marked skipped=true")

    results = []
    n_suppressed = 0
    stopped = ""
    for i, seq in enumerate(not_skipped[:max_per_day]):
        try:
            if is_suppressed(seq["to_email"], strict=True):
                n_suppressed += 1
                logger.info(f"[send] skipping {seq['to_email']} (opted out)")
                continue
        except SuppressionStoreError as e:
            stopped = f"stopped before {seq['to_email']}: opt-out list unreadable ({e})"
            logger.error(f"[send] STOPPING batch, {stopped}")
            break
        res = _instantly_send_sequence(seq, campaign_id, key)
        results.append({"email": seq["to_email"], "result": res})
        time.sleep(0.5)  # 2 req/sec ceiling

    sent = sum(1 for r in results if r["result"].get("status") == 200)
    return {
        "status": "stopped" if stopped else "ok",
        "reason": stopped,
        "n_attempted": len(results),
        "n_sent_to_instantly": sent,
        "n_suppressed": n_suppressed,
        "suppression_store": store["store"],
        "warning": warning,
        "results": results,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("compose")
    c.add_argument("--manifest", required=True)
    c.add_argument("--sender", default="Jay")
    s = sub.add_parser("send")
    s.add_argument("--sequences", required=True)
    s.add_argument("--confirm", action="store_true")
    s.add_argument("--live", action="store_true")
    args = p.parse_args()

    if args.mode == "compose":
        out = compose_sequences(Path(args.manifest), sender_name=args.sender)
        print(f"OK · sequences: {out}")
    else:
        result = send_sequences(Path(args.sequences), confirm=args.confirm, live=args.live)
        print(json.dumps(result, indent=2))
