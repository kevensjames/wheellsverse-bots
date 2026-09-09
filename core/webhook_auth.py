"""Provider authentication for inbound webhooks. Pure stdlib, no framework, no I/O except the
idempotency marker.

WHY THIS EXISTS. Four receivers on App A accepted unauthenticated POSTs from anyone:

    /api/telegram/webhook   read the right header, but only `if expected_secret` — unset meant no
                            check at all, and it compared with `!=`
    /api/whatsapp/webhook   no authentication of any kind; dispatched straight into message handling
    /api/beehiiv/webhook    token in a QUERY STRING, and its own docstring said "If it isn't set, we
                            accept any request (the URL itself is the shared secret)"
    /api/payhip/webhook     no authentication; a forged POST wrote a financial record into the sales
                            file and fired a Telegram notification

A secret in a URL is not private: it lands in edge logs, access logs, Referer headers, browser
history and analytics, none of which can revoke it. And "accept everything when unconfigured" is the
same fail-open that made the owner surface anonymous two incidents ago. Missing configuration is a
misconfiguration, not permission — every verifier here returns UNAVAILABLE for it, and the caller
turns that into 503, never a 200.

EACH PROVIDER'S CONTRACT IS THE PROVIDER'S, NOT OURS. Nothing here is invented:

  Telegram  `secret_token` on setWebhook is echoed in `X-Telegram-Bot-Api-Secret-Token` on every
            request, 1-256 chars of [A-Za-z0-9_-]. It is a shared secret, not a payload signature,
            so it cannot bind to the body — which is exactly why it must also be constant-time
            compared and required.
  Meta      `X-Hub-Signature-256: sha256=<hex>`, HMAC-SHA256 of the payload keyed by the App Secret.
            The GET handshake (hub.mode / hub.challenge / hub.verify_token) is a SEPARATE mechanism
            and must never be a way into authenticated POST delivery.
  Svix      Beehiiv delivers through Svix: `svix-id`, `svix-timestamp`, `svix-signature`. Signed
            content is `{id}.{timestamp}.{body}`; the secret is `whsec_<base64>` and the base64 part
            is DECODED to key bytes; output is base64; the header holds space-delimited `v1,<sig>`
            entries so key rotation keeps working.
  Payhip    Payhip documents a `signature` field computed as `hash('sha256', $apiKey)` — the API key
            alone. That value is IDENTICAL on every request and is not a signature over the payload
            at all. It excludes an anonymous stranger, and nothing more: anyone who ever observes one
            delivery can replay it forever and forge every other field. Payhip's public API exposes
            only coupons and license keys, so there is no transaction endpoint to confirm a sale
            against. See `payhip_trust_level()` — this module refuses to pretend otherwise.

THE RAW BODY IS THE MESSAGE. Signatures cover the exact bytes sent. Re-serialising parsed JSON
changes key order, whitespace and unicode escaping, and the signature stops matching — so callers
read the body ONCE, verify those bytes, and parse from the same bytes.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Optional, Tuple

# Outcomes. UNAVAILABLE is distinct from INVALID on purpose: one is our fault and must not look like
# the caller's, and it is the only one that maps to 503.
OK = "OK"
UNAVAILABLE = "WEBHOOK_AUTH_UNAVAILABLE"
MISSING = "SIGNATURE_MISSING"
MALFORMED = "SIGNATURE_MALFORMED"
INVALID = "SIGNATURE_INVALID"
EXPIRED = "TIMESTAMP_OUTSIDE_TOLERANCE"

Result = Tuple[str, str]  # (outcome, human-readable reason — safe to log, never echoed to caller)

DEFAULT_TOLERANCE_SECONDS = 300


def _eq(a: str, b: str) -> bool:
    """Constant-time compare of two str values, encoding first so non-ASCII cannot raise."""
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"),
                               b.encode("utf-8", "surrogatepass"))


# ── Telegram ──────────────────────────────────────────────────────────────────────────────────────
def verify_telegram(header_value: Optional[str], expected_secret: Optional[str]) -> Result:
    """`X-Telegram-Bot-Api-Secret-Token` must be present and equal to the configured secret.

    The old code was `if expected_secret and header != expected_secret: 403`. With the variable
    unset the whole check vanished and every anonymous POST was processed as a real Telegram update.
    Configuration is not authorization: unset is UNAVAILABLE.
    """
    if not (expected_secret or "").strip():
        return UNAVAILABLE, "TELEGRAM_WEBHOOK_SECRET is not configured"
    if not (header_value or "").strip():
        return MISSING, "X-Telegram-Bot-Api-Secret-Token absent"
    if not _eq(header_value, expected_secret):
        return INVALID, "secret token mismatch"
    return OK, "telegram secret token verified"


# ── Meta / WhatsApp ───────────────────────────────────────────────────────────────────────────────
def verify_meta_signature(raw_body: bytes, header_value: Optional[str],
                          app_secret: Optional[str]) -> Result:
    """`X-Hub-Signature-256: sha256=<hex>`, HMAC-SHA256 over the RAW body, keyed by the App Secret."""
    if not (app_secret or "").strip():
        return UNAVAILABLE, "WHATSAPP_APP_SECRET is not configured"
    if not (header_value or "").strip():
        return MISSING, "X-Hub-Signature-256 absent"
    value = header_value.strip()
    if not value.startswith("sha256="):
        # sha1= is Meta's legacy header on a DIFFERENT header name and is not accepted here.
        return MALFORMED, "header is not of the form sha256=<hex>"
    provided = value[len("sha256="):].strip()
    if not provided:
        return MALFORMED, "empty digest"
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Compare case-insensitively: the digest is hex, and hex case carries no meaning. Lowercasing
    # both sides keeps the comparison constant-time while accepting either casing.
    if not _eq(provided.lower(), expected):
        return INVALID, "body does not match signature"
    return OK, "meta signature verified"


def verify_meta_handshake(mode: Optional[str], token: Optional[str],
                          challenge: Optional[str], expected_token: Optional[str]) -> Result:
    """The GET subscription handshake — a SEPARATE mechanism from POST delivery.

    Kept apart deliberately. The handshake proves we control the endpoint at subscribe time; it says
    nothing about any later payload. Letting one satisfy the other is how a verification endpoint
    becomes an authentication bypass.
    """
    if not (expected_token or "").strip():
        return UNAVAILABLE, "WHATSAPP_VERIFY_TOKEN is not configured"
    if mode != "subscribe":
        return MALFORMED, "hub.mode is not 'subscribe'"
    if not (token or "").strip():
        return MISSING, "hub.verify_token absent"
    if not _eq(token, expected_token):
        return INVALID, "hub.verify_token mismatch"
    if challenge is None or challenge == "":
        return MALFORMED, "hub.challenge absent"
    return OK, "handshake verified"


# ── Svix / Beehiiv ────────────────────────────────────────────────────────────────────────────────
def verify_svix(raw_body: bytes, svix_id: Optional[str], svix_timestamp: Optional[str],
                svix_signature: Optional[str], secret: Optional[str],
                tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
                now: Optional[float] = None) -> Result:
    """Svix: HMAC-SHA256 over `{svix-id}.{svix-timestamp}.{raw body}`, base64 out.

    The secret is `whsec_<base64>`; the base64 part is DECODED to key bytes. HMAC-ing the literal
    string instead is the classic mistake here and produces a verifier that rejects everything real.

    The header carries space-delimited `v1,<base64>` entries — more than one during key rotation —
    so every v1 entry is tried and any match passes. The timestamp is bound INTO the signed content,
    so a replayed delivery cannot have its timestamp edited without breaking the signature; the
    tolerance check then makes an old-but-genuine delivery stop being accepted.
    """
    if not (secret or "").strip():
        return UNAVAILABLE, "BEEHIIV_WEBHOOK_SECRET is not configured"
    if not (svix_id or "").strip() or not (svix_timestamp or "").strip() or not (svix_signature or "").strip():
        return MISSING, "svix-id, svix-timestamp or svix-signature absent"

    try:
        ts = int(svix_timestamp)
    except (TypeError, ValueError):
        return MALFORMED, "svix-timestamp is not an integer"
    current = time.time() if now is None else now
    if abs(current - ts) > tolerance_seconds:
        # Both directions: far-past is a replay, far-future is a forged or clock-skewed sender.
        return EXPIRED, f"timestamp {ts} outside +/-{tolerance_seconds}s"

    raw_secret = secret.strip()
    if raw_secret.startswith("whsec_"):
        raw_secret = raw_secret[len("whsec_"):]
    try:
        key = base64.b64decode(raw_secret)
    except Exception:
        return UNAVAILABLE, "BEEHIIV_WEBHOOK_SECRET is not valid base64"
    if not key:
        return UNAVAILABLE, "BEEHIIV_WEBHOOK_SECRET decoded to empty"

    signed = svix_id.encode("utf-8") + b"." + svix_timestamp.encode("utf-8") + b"." + raw_body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    matched = False
    for part in svix_signature.split(" "):
        part = part.strip()
        if not part or "," not in part:
            continue
        version, _, candidate = part.partition(",")
        if version != "v1":
            continue
        # Do not break on match: comparing every v1 entry keeps the work independent of WHERE the
        # matching signature sits in the header, so the loop leaks nothing through timing.
        if _eq(candidate, expected):
            matched = True
    if not matched:
        return INVALID, "no v1 signature matched"
    return OK, "svix signature verified"


# ── Payhip ────────────────────────────────────────────────────────────────────────────────────────
def payhip_trust_level() -> str:
    """What Payhip's mechanism actually establishes. Named so no caller can round it up by accident.

    Payhip documents `signature = hash('sha256', $apiKey)`. That is a constant, so it authenticates
    the SENDER weakly and the PAYLOAD not at all. Anyone who observes one delivery — a log, a proxy,
    a support ticket, a screenshot — can forge every field of every future one. Payhip's public API
    covers coupons and license keys only, so there is no transaction endpoint to confirm a sale
    against either.
    """
    return "SHARED_SECRET_ONLY_NO_PAYLOAD_BINDING_NO_SERVER_CONFIRMATION"


def verify_payhip_static(payload_signature: Optional[str], api_key: Optional[str]) -> Result:
    """Verify Payhip's static `signature` field against sha256(api_key).

    Passing this means "the sender knows our API key". It does NOT mean the fields are genuine, so a
    caller must not treat a verified Payhip callback as a confirmed financial event.
    """
    if not (api_key or "").strip():
        return UNAVAILABLE, "PAYHIP_API_KEY is not configured"
    if not (payload_signature or "").strip():
        return MISSING, "payload has no signature field"
    expected = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()
    if not _eq(payload_signature.strip().lower(), expected):
        return INVALID, "signature does not match sha256(api_key)"
    return OK, "payhip shared secret verified (payload NOT authenticated)"


# ── Idempotency ───────────────────────────────────────────────────────────────────────────────────
_DEFAULT_STORE = Path("data/webhook_events")


def claim_event(namespace: str, event_id: str, store: Optional[Path] = None) -> bool:
    """Claim a provider event id. True = first time (process it). False = already seen (ack, do nothing).

    Atomicity comes from the filesystem, not from a lock: `O_CREAT | O_EXCL` either creates the
    marker or fails with EEXIST, and that decision is made in one syscall. Two workers racing on the
    same redelivery cannot both win, which a read-then-write check cannot promise. No database, no
    lock file, no cleanup daemon.

    A blank event_id is NOT claimable — a provider that sends no id gets no idempotency, and the
    caller must decide what that means rather than have every such delivery collide on "".
    """
    if not (namespace or "").strip() or not (event_id or "").strip():
        return True
    root = (store or _DEFAULT_STORE) / namespace
    # A provider id is untrusted input and must never escape the namespace directory, so it is
    # hashed rather than used as a filename. That also bounds the length and the character set.
    marker = root / hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:32]
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False
        # Store unavailable (read-only fs, permissions). Fail OPEN on idempotency only: the delivery
        # is already cryptographically verified by this point, so the worst case is a duplicate
        # effect, whereas failing closed would drop a genuine event permanently. This is the one
        # place in this module that does not fail closed, and that is deliberate.
        return True
    os.close(fd)
    return True


def demo() -> None:
    """Zero-framework self-check: python3 core/webhook_auth.py"""
    import json
    import tempfile

    # Telegram: unset is UNAVAILABLE, not open.
    assert verify_telegram("x", None)[0] == UNAVAILABLE
    assert verify_telegram("x", "")[0] == UNAVAILABLE
    assert verify_telegram(None, "s3cret")[0] == MISSING
    assert verify_telegram("wrong", "s3cret")[0] == INVALID
    assert verify_telegram("s3cret", "s3cret")[0] == OK

    # Meta: HMAC over the exact bytes.
    body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
    secret = "app-secret"
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_meta_signature(body, good, secret)[0] == OK
    assert verify_meta_signature(body, good.upper().replace("SHA256=", "sha256="), secret)[0] == OK
    assert verify_meta_signature(body + b" ", good, secret)[0] == INVALID   # one byte changes it
    assert verify_meta_signature(body, good, None)[0] == UNAVAILABLE
    assert verify_meta_signature(body, None, secret)[0] == MISSING
    assert verify_meta_signature(body, "sha1=abc", secret)[0] == MALFORMED
    assert verify_meta_signature(body, "sha256=", secret)[0] == MALFORMED

    # Handshake is separate and cannot stand in for a signature.
    assert verify_meta_handshake("subscribe", "vt", "1234", "vt")[0] == OK
    assert verify_meta_handshake("subscribe", "no", "1234", "vt")[0] == INVALID
    assert verify_meta_handshake("unsubscribe", "vt", "1234", "vt")[0] == MALFORMED
    assert verify_meta_handshake("subscribe", "vt", None, "vt")[0] == MALFORMED
    assert verify_meta_handshake("subscribe", "vt", "1234", None)[0] == UNAVAILABLE

    # Svix: signed content is id.timestamp.body, key is the DECODED base64 half.
    key = os.urandom(24)
    whsec = "whsec_" + base64.b64encode(key).decode()
    sid, sts, sbody = "msg_123", str(int(time.time())), b'{"event":"subscriber.created"}'
    sig = base64.b64encode(hmac.new(
        key, f"{sid}.{sts}.".encode() + sbody, hashlib.sha256).digest()).decode()
    assert verify_svix(sbody, sid, sts, f"v1,{sig}", whsec)[0] == OK
    assert verify_svix(sbody, sid, sts, f"v1,other v1,{sig}", whsec)[0] == OK      # rotation
    assert verify_svix(sbody, sid, sts, f"v2,{sig}", whsec)[0] == INVALID          # wrong version
    assert verify_svix(sbody, "msg_other", sts, f"v1,{sig}", whsec)[0] == INVALID  # id is bound
    assert verify_svix(sbody + b"x", sid, sts, f"v1,{sig}", whsec)[0] == INVALID   # body is bound
    assert verify_svix(sbody, sid, sts, f"v1,{sig}", whsec, now=time.time() + 9999)[0] == EXPIRED
    assert verify_svix(sbody, sid, sts, f"v1,{sig}", whsec, now=time.time() - 9999)[0] == EXPIRED
    assert verify_svix(sbody, sid, sts, f"v1,{sig}", None)[0] == UNAVAILABLE
    assert verify_svix(sbody, sid, "not-a-number", f"v1,{sig}", whsec)[0] == MALFORMED
    assert verify_svix(sbody, None, sts, f"v1,{sig}", whsec)[0] == MISSING
    # HMAC-ing the literal secret string instead of the decoded key must NOT verify.
    wrong = base64.b64encode(hmac.new(
        whsec.encode(), f"{sid}.{sts}.".encode() + sbody, hashlib.sha256).digest()).decode()
    assert verify_svix(sbody, sid, sts, f"v1,{wrong}", whsec)[0] == INVALID

    # Payhip: static, and named as such.
    api_key = "payhip-api-key"
    assert verify_payhip_static(hashlib.sha256(api_key.encode()).hexdigest(), api_key)[0] == OK
    assert verify_payhip_static("deadbeef", api_key)[0] == INVALID
    assert verify_payhip_static(None, api_key)[0] == MISSING
    assert verify_payhip_static("x", None)[0] == UNAVAILABLE
    assert "NO_PAYLOAD_BINDING" in payhip_trust_level()

    # Idempotency: first wins, and it is one syscall.
    with tempfile.TemporaryDirectory() as d:
        store = Path(d)
        assert claim_event("beehiiv", "evt_1", store) is True
        assert claim_event("beehiiv", "evt_1", store) is False
        assert claim_event("beehiiv", "evt_2", store) is True
        assert claim_event("telegram", "evt_1", store) is True   # namespaced separately
        assert claim_event("beehiiv", "", store) is True         # no id -> no idempotency
        # A hostile id must not escape the namespace directory.
        assert claim_event("beehiiv", "../../../etc/passwd", store) is True
        assert not (store / "etc").exists()
        assert sorted(p.name for p in (store / "beehiiv").iterdir()) == sorted(
            hashlib.sha256(x.encode()).hexdigest()[:32]
            for x in ("evt_1", "evt_2", "../../../etc/passwd"))

    print("webhook_auth: all checks passed")


if __name__ == "__main__":
    demo()
