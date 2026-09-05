"""§8/§94 Gesture + camera policy (Phase 8, BACKEND) — a typed SEAM, not a recognizer.

HONESTY: this repo has NO certified local gesture model and this module adds none (no dependency, no CDN
script, no model download). A hand-tracking library is third-party supply chain and must first pass the
capability/manifest certification path (capability.manifest.CapabilityManifest → Certification.CERTIFIED,
§39/§82 supply-chain scan) before it may be injected into the ``recognizer`` seam. Until then the seam
reports RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED and the dashboard says so.

NON-NEGOTIABLES (§8/§94, enforced here, not by convention):
  - Camera OFF by default: KAI_CAMERA_ENABLED (config.py) default False AND an explicit per-SESSION owner
    enable that is passed per request and is NEVER read from persisted settings (camera_allowed).
  - A VISIBLE always-on indicator whenever the camera is open (INDICATOR_REQUIRED, constant True).
  - Inference is LOCAL-ONLY: no frame/image/video ever leaves the device (FRAMES_LEAVE_DEVICE, constant
    False). This process never receives pixels — it receives a TYPED gesture event (name+confidence+ts).
  - NO biometric / identity / emotion inference (BIOMETRIC_INFERENCE, constant False).
  - Gestures map ONLY to non-consequential UI actions (stop/dismiss/next/previous/scroll/open_drawer).
    map_gesture can NEVER return anything in CONSEQUENTIAL_ACTIONS (asserted at import + at return).
  - A gesture NEVER approves/confirms/executes/spends/changes authority: channel 'gesture' is refused by
    approval_dialog (_UNAUTHORIZED_CHANNELS) exactly like voice — this module adds no second rule.
  - Gestures never bypass auth: a non-owner principal → REFUSED.
  - Audit events are exactly GESTURE_AUDIT_KEYS — never a frame/image/embedding field (asserted).

Pure stdlib + capability.manifest; DB-free; testable as a plain python3 script (test_gesture_policy.py).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from app.services.capability.manifest import Certification


# ── typed vocabulary (kept small on purpose) ─────────────────────────────────────────────────────────
class Gesture(str, Enum):
    OPEN_PALM = "OPEN_PALM"
    SWIPE_LEFT = "SWIPE_LEFT"
    SWIPE_RIGHT = "SWIPE_RIGHT"
    THUMBS_DOWN = "THUMBS_DOWN"
    POINT_UP = "POINT_UP"


# The ONLY actions a gesture may ever produce — all non-consequential UI navigation.
UI_ACTIONS = frozenset({"stop", "dismiss", "next", "previous", "scroll", "open_drawer"})

# Hard invariant: map_gesture can never return one of these (authority-changing / consequential).
CONSEQUENTIAL_ACTIONS = frozenset({"approve", "confirm", "execute", "spend", "enable", "merge", "deploy", "policy"})

GESTURE_ACTIONS: dict[Gesture, str] = {
    Gesture.OPEN_PALM: "stop",          # → KAI.stop (the single stop path)
    Gesture.SWIPE_LEFT: "next",
    Gesture.SWIPE_RIGHT: "previous",
    Gesture.THUMBS_DOWN: "dismiss",
    Gesture.POINT_UP: "open_drawer",
}
assert set(GESTURE_ACTIONS.values()) <= UI_ACTIONS
assert not (set(GESTURE_ACTIONS.values()) & CONSEQUENTIAL_ACTIONS)
assert not (UI_ACTIONS & CONSEQUENTIAL_ACTIONS)

CONFIDENCE_THRESHOLD = 0.80
REFUSED = "REFUSED"
CHANNEL = "gesture"

# Constants, documented: these are policy, not settings — nothing can flip them at runtime.
INDICATOR_REQUIRED = True        # a visible camera-on indicator is MANDATORY whenever the camera is open
FRAMES_LEAVE_DEVICE = False      # no frame/image/video is ever uploaded, fetched, or seen server-side
BIOMETRIC_INFERENCE = False      # no identity / face / emotion inference, ever

RECOGNIZER_STATUS = "RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED"
RECOGNIZER_CERT_PATH = ("app/services/capability/manifest.py — a hand-tracking library must be onboarded as a "
                        "CapabilityManifest and reach Certification.CERTIFIED (§39/§82 supply-chain scan) "
                        "before it may be injected into the recognizer seam")


@dataclass
class GestureDecision:
    gesture: str
    confidence: float
    action: str                  # one of UI_ACTIONS, or REFUSED
    reason: str
    channel: str = CHANNEL
    authority: str = "NONE"      # a gesture carries no authority — descriptive, never a grant

    def as_dict(self) -> dict:
        return asdict(self)


def map_gesture(name, confidence, principal_role) -> GestureDecision:
    """Pure: typed gesture → a NON-CONSEQUENTIAL UI action, or REFUSED (unknown gesture, confidence below
    threshold, non-owner). Never raises on bad input; never returns a consequential action."""
    n = str(name or "").strip().upper()
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        c = 0.0
    if principal_role != "owner":
        out = GestureDecision(n, c, REFUSED, "gestures never bypass auth — owner session required (§75)")
    elif n not in Gesture.__members__:
        out = GestureDecision(n, c, REFUSED, "unknown gesture — not in the typed vocabulary")
    elif c < CONFIDENCE_THRESHOLD:
        out = GestureDecision(n, c, REFUSED, f"confidence {c:.2f} below threshold {CONFIDENCE_THRESHOLD}")
    else:
        out = GestureDecision(n, c, GESTURE_ACTIONS[Gesture(n)], "non-consequential UI action")
    assert out.action == REFUSED or out.action in UI_ACTIONS
    assert out.action not in CONSEQUENTIAL_ACTIONS
    return out


# ── recognizer seam (honestly UNAVAILABLE until a CERTIFIED, LOCAL engine is injected) ──────────────
def recognizer_status(recognizer=None) -> dict:
    """Mirrors voice_session.local_wake_word_status. None → NOT_CERTIFIED. An injected engine must be
    on-device AND certified through the manifest path; anything else stays unavailable (fail closed)."""
    base = {"status": RECOGNIZER_STATUS, "available": False, "engine": None, "is_local": False,
            "certification": None, "certification_path": RECOGNIZER_CERT_PATH}
    if recognizer is None:
        return {**base, "reason": "no certified local gesture recognizer in this repo — none was added"}
    try:
        is_local = bool(recognizer.is_local())
        cert = str(getattr(recognizer, "certification", "") or "")
        engine = getattr(recognizer, "engine_name", None)
    except Exception:
        return {**base, "reason": "recognizer seam errored — fail closed"}
    if not is_local:
        return {**base, "engine": engine, "certification": cert,
                "reason": "recognizer is not on-device — frames must never leave the device (§94)"}
    if cert != Certification.CERTIFIED.value:
        return {**base, "engine": engine, "is_local": True, "certification": cert,
                "reason": "local recognizer present but NOT certified via the capability/manifest path"}
    return {**base, "status": "AVAILABLE", "available": True, "engine": engine, "is_local": True,
            "certification": cert, "reason": ""}


# ── session policy ──────────────────────────────────────────────────────────────────────────────────
class GestureSessionPolicy:
    indicator_required = INDICATOR_REQUIRED
    frames_leave_device = FRAMES_LEAVE_DEVICE
    biometric_inference = BIOMETRIC_INFERENCE

    @staticmethod
    def camera_allowed(settings, session_flag) -> bool:
        """KAI_CAMERA_ENABLED AND an explicit per-session owner enable. The session enable is the literal
        bool True passed by the caller for THIS session — it is never read from ``settings`` or any
        persisted store, so a persisted 'camera_enabled: true' can never open the camera by itself."""
        return bool(getattr(settings, "KAI_CAMERA_ENABLED", False)) and session_flag is True

    @staticmethod
    def capabilities(settings, recognizer=None) -> dict:
        flag = bool(getattr(settings, "KAI_CAMERA_ENABLED", False))
        return {
            "enabled": flag,
            "camera": "AVAILABLE_SESSION" if flag else "OFF",   # never ON — a session enable is still required
            "session_enable_required": True,
            "session_enable_persisted": False,
            "indicator": "REQUIRED",
            "inference": "LOCAL_ONLY",
            "frames_leave_device": FRAMES_LEAVE_DEVICE,
            "recognizer": recognizer_status(recognizer),
            "approval_by_gesture": REFUSED,
            "biometrics": "NEVER",
            "vocabulary": {g.value: a for g, a in GESTURE_ACTIONS.items()},
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "contract": "typed gesture EVENT (name+confidence+ts) → non-consequential UI action only; "
                        "consequential intents go through POST /admin/holding/command (typed owner action)",
        }


# ── audit event shape — exactly these 10 keys, never a frame/image/embedding ────────────────────────
GESTURE_AUDIT_KEYS = frozenset({"gesture", "confidence", "action", "principal", "ts", "session_id",
                                "outcome", "channel", "frames_recorded", "biometric"})
_FORBIDDEN_AUDIT_KEYS = frozenset({"frame", "frames", "image", "video", "embedding", "landmarks", "pixels",
                                   "snapshot", "face", "identity"})
assert not (GESTURE_AUDIT_KEYS & _FORBIDDEN_AUDIT_KEYS)


def gesture_event(*, gesture, confidence, action, principal, ts, session_id, outcome) -> dict:
    """The only audit record shape for a gesture. Keyword-only, fixed signature: there is no parameter a
    caller could use to smuggle pixels in."""
    rec = {"gesture": str(gesture), "confidence": float(confidence or 0.0), "action": str(action),
           "principal": str(principal), "ts": str(ts), "session_id": str(session_id), "outcome": str(outcome),
           "channel": CHANNEL, "frames_recorded": False, "biometric": False}
    assert set(rec) == GESTURE_AUDIT_KEYS and not (set(rec) & _FORBIDDEN_AUDIT_KEYS)
    return rec


if __name__ == "__main__":
    from app.services.holding.test_gesture_policy import run
    raise SystemExit(0 if run() else 1)
