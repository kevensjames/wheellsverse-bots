"""§8/§94 gesture + camera policy checks (Phase 8). Zero-framework — mirrors test_voice_session.py.
Run (from backend/):
    python3 -m app.services.holding.test_gesture_policy
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding.gesture_policy import (   # noqa: E402
    Gesture, GESTURE_ACTIONS, UI_ACTIONS, CONSEQUENTIAL_ACTIONS, CONFIDENCE_THRESHOLD, REFUSED,
    INDICATOR_REQUIRED, FRAMES_LEAVE_DEVICE, BIOMETRIC_INFERENCE, RECOGNIZER_STATUS,
    GESTURE_AUDIT_KEYS, GestureSessionPolicy, map_gesture, recognizer_status, gesture_event)
from app.services.holding.approval_dialog import ConfirmationStatus, interpret_confirmation, authorize   # noqa: E402


class _Rec:
    def __init__(self, local, cert, name="fake-hand-tracker"):
        self._local, self.certification, self.engine_name = local, cert, name
    def is_local(self): return self._local


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    OFF = SimpleNamespace(KAI_CAMERA_ENABLED=False)
    ON = SimpleNamespace(KAI_CAMERA_ENABLED=True)
    P = GestureSessionPolicy

    # ── config: KAI_CAMERA_ENABLED exists and defaults False ───────────────────────────────────────
    from app.config import settings as cfg
    ck("KAI_CAMERA_ENABLED default is False", getattr(cfg, "KAI_CAMERA_ENABLED", None) is False)
    ck("real settings → camera OFF, not allowed even with a session enable (flag off)",
       P.camera_allowed(cfg, True) is False and P.capabilities(cfg)["camera"] == "OFF")

    # ── camera_allowed = flag AND explicit per-session enable; never from persisted settings ───────
    ck("flag off + no session enable → False", P.camera_allowed(OFF, False) is False)
    ck("flag off + session enable → False (flag is the master)", P.camera_allowed(OFF, True) is False)
    ck("flag on + no session enable → False (session enable is mandatory)", P.camera_allowed(ON, False) is False)
    ck("flag on + explicit session enable → True", P.camera_allowed(ON, True) is True)
    persisted = SimpleNamespace(KAI_CAMERA_ENABLED=True, camera_enabled=True, camera_session_enabled=True,
                                gesture_enabled=True)
    ck("a persisted 'camera_enabled/session_enabled: true' in settings NEVER opens the camera by itself",
       P.camera_allowed(persisted, False) is False and P.camera_allowed(persisted, None) is False)
    ck("session enable must be the literal bool True (truthy strings/dicts/1 are not an explicit enable)",
       all(P.camera_allowed(ON, v) is False for v in ("1", "true", 1, {"on": True}, [True])))

    # ── constants (policy, not settings) ──────────────────────────────────────────────────────────
    ck("indicator_required is True (constant)", INDICATOR_REQUIRED is True and P.indicator_required is True)
    ck("frames_leave_device is False (constant)", FRAMES_LEAVE_DEVICE is False and P.frames_leave_device is False)
    ck("biometric_inference is False (constant)", BIOMETRIC_INFERENCE is False and P.biometric_inference is False)

    # ── map_gesture: the vocabulary maps ONLY to non-consequential UI actions ─────────────────────
    expect = {"OPEN_PALM": "stop", "SWIPE_LEFT": "next", "SWIPE_RIGHT": "previous",
              "THUMBS_DOWN": "dismiss", "POINT_UP": "open_drawer"}
    ck("vocabulary is exactly the 5 typed gestures", {g.value for g in Gesture} == set(expect))
    for g, a in expect.items():
        d = map_gesture(g, 0.95, "owner")
        ck(f"{g} @0.95 owner → '{a}' (channel=gesture, authority NONE)",
           d.action == a and d.channel == "gesture" and d.authority == "NONE" and d.as_dict()["action"] == a)
    ck("every mapped action ∈ UI_ACTIONS and ∉ CONSEQUENTIAL_ACTIONS",
       set(GESTURE_ACTIONS.values()) <= UI_ACTIONS and not (set(GESTURE_ACTIONS.values()) & CONSEQUENTIAL_ACTIONS))
    ck("CONSEQUENTIAL_ACTIONS covers approve/confirm/execute/spend/enable/merge/deploy/policy",
       {"approve", "confirm", "execute", "spend", "enable", "merge", "deploy", "policy"} <= CONSEQUENTIAL_ACTIONS)
    ck("lower-case / padded names normalize", map_gesture(" open_palm ", 0.9, "owner").action == "stop")

    # ── REFUSED paths ─────────────────────────────────────────────────────────────────────────────
    ck("unknown gesture → REFUSED", map_gesture("FIST", 0.99, "owner").action == REFUSED)
    ck("consequential word smuggled as a gesture name → REFUSED (not in vocabulary)",
       all(map_gesture(w, 0.99, "owner").action == REFUSED for w in CONSEQUENTIAL_ACTIONS))
    ck("confidence below threshold → REFUSED",
       map_gesture("OPEN_PALM", CONFIDENCE_THRESHOLD - 0.01, "owner").action == REFUSED)
    ck("non-numeric / None confidence → REFUSED (no crash)",
       map_gesture("OPEN_PALM", None, "owner").action == REFUSED
       and map_gesture("OPEN_PALM", "high", "owner").action == REFUSED)
    ck("non-owner (operator/viewer/None) → REFUSED — gestures never bypass auth",
       all(map_gesture("OPEN_PALM", 0.99, r).action == REFUSED for r in ("operator", "viewer", None, "")))
    ck("None gesture → REFUSED (no crash)", map_gesture(None, 0.99, "owner").action == REFUSED)

    # ── hard invariant: brute-force the input space — map_gesture NEVER returns a consequential action ──
    names = list(expect) + list(CONSEQUENTIAL_ACTIONS) + ["", None, "APPROVE_42", "DEPLOY"]
    outs = {map_gesture(n, c, r).action for n in names for c in (0.0, 0.5, 0.79, 0.8, 1.0, 5.0)
            for r in ("owner", "operator", None)}
    ck("over the whole input grid, outputs ⊆ UI_ACTIONS ∪ {REFUSED} and ∩ CONSEQUENTIAL = ∅",
       outs <= (UI_ACTIONS | {REFUSED}) and not (outs & CONSEQUENTIAL_ACTIONS))

    # ── capabilities(settings): honest dashboard truth ────────────────────────────────────────────
    c_off, c_on = P.capabilities(OFF), P.capabilities(ON)
    ck("flag off → camera OFF; flag on → AVAILABLE_SESSION (never plain ON)",
       c_off["camera"] == "OFF" and c_on["camera"] == "AVAILABLE_SESSION"
       and c_off["enabled"] is False and c_on["enabled"] is True)
    ck("session enable required + never persisted",
       c_on["session_enable_required"] is True and c_on["session_enable_persisted"] is False)
    ck("indicator REQUIRED, inference LOCAL_ONLY, frames_leave_device False",
       c_on["indicator"] == "REQUIRED" and c_on["inference"] == "LOCAL_ONLY" and c_on["frames_leave_device"] is False)
    ck("recognizer is RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED with a pointer to capability/manifest cert path",
       c_on["recognizer"]["status"] == RECOGNIZER_STATUS == "RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED"
       and c_on["recognizer"]["available"] is False
       and "capability/manifest.py" in c_on["recognizer"]["certification_path"]
       and "CERTIFIED" in c_on["recognizer"]["certification_path"])
    ck("approval_by_gesture REFUSED, biometrics NEVER", c_on["approval_by_gesture"] == "REFUSED" and c_on["biometrics"] == "NEVER")
    ck("vocabulary + threshold exposed for the UI",
       c_on["vocabulary"] == expect and c_on["confidence_threshold"] == CONFIDENCE_THRESHOLD)

    # ── recognizer seam: fail closed until a LOCAL + CERTIFIED engine is injected ────────────────
    ck("no recognizer → NOT_CERTIFIED", recognizer_status(None)["status"] == RECOGNIZER_STATUS)
    ck("injected LOCAL but uncertified (EXPERIMENTAL) → still NOT_CERTIFIED",
       recognizer_status(_Rec(True, "EXPERIMENTAL"))["status"] == RECOGNIZER_STATUS)
    ck("injected CERTIFIED but NOT local (cloud vision) → NOT_CERTIFIED / unavailable (frames must not leave)",
       recognizer_status(_Rec(False, "CERTIFIED"))["status"] == RECOGNIZER_STATUS
       and recognizer_status(_Rec(False, "CERTIFIED"))["is_local"] is False)
    ck("injected LOCAL + CERTIFIED → AVAILABLE (the seam works, honestly gated)",
       recognizer_status(_Rec(True, "CERTIFIED"))["status"] == "AVAILABLE")
    class _Boom:
        def is_local(self): raise RuntimeError("x")
    ck("seam errors → fail closed NOT_CERTIFIED", recognizer_status(_Boom())["status"] == RECOGNIZER_STATUS)

    # ── audit event: exactly 10 keys, never pixels ───────────────────────────────────────────────
    ev = gesture_event(gesture="OPEN_PALM", confidence=0.93, action="stop", principal="kai-owner",
                       ts="2026-09-04T00:00:00+00:00", session_id="s1", outcome="APPLIED")
    ck("audit event has exactly the 10 documented keys", set(ev) == GESTURE_AUDIT_KEYS and len(ev) == 10)
    ck("channel='gesture', frames_recorded=False, biometric=False",
       ev["channel"] == "gesture" and ev["frames_recorded"] is False and ev["biometric"] is False)
    ck("no frame/image/video/embedding/landmarks field can exist in the event",
       not any(k in ev for k in ("frame", "frames", "image", "video", "embedding", "landmarks", "pixels", "face")))
    try:
        gesture_event(gesture="OPEN_PALM", confidence=0.9, action="stop", principal="o", ts="t",
                      session_id="s", outcome="x", frame=b"\x00")
        smuggled = True
    except TypeError:
        smuggled = False
    ck("passing frame= to gesture_event is a TypeError (fixed signature — nothing can carry pixels)", not smuggled)

    # ── approval_dialog refuses channel=gesture identically to voice (one rule, no copy) ──────────
    d = interpret_confirmation("approve 42", "42", channel="gesture")
    ck("even explicit 'approve 42' over channel=gesture → REFUSED_CHANNEL, not authorized (§75)",
       d.authorized is False and d.status == ConfirmationStatus.REFUSED_CHANNEL.value)
    dv = interpret_confirmation("approve 42", "42", channel="voice")
    ck("gesture and voice refusals are the SAME status (single rule)", d.status == dv.status)
    ck("channel=camera is refused too", interpret_confirmation("approve 42", "42", channel="camera").status
       == ConfirmationStatus.REFUSED_CHANNEL.value)
    writes = {"n": 0}
    def decider(*a, **k): writes["n"] += 1; return {"id": 42, "status": "approved"}
    out = authorize("42", principal="kai-owner", utterance="approve 42", channel="gesture",
                    decider=decider, fetch=lambda i: {"id": 42, "status": "proposed"})
    ck("authorize(channel=gesture) writes NOTHING durable (decider never called)",
       out["authorized"] is False and writes["n"] == 0 and out["record"] is None)

    # ── HONESTY: no model, no dependency, no CDN, no network in the policy module ─────────────────
    src = (Path(__file__).resolve().parent / "gesture_policy.py").read_text()
    imports = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    ck("gesture_policy imports only stdlib + capability.manifest (no mediapipe/tf/onnx/cv2/requests)",
       all(any(ln.startswith(p) for p in ("from __future__", "from dataclasses", "from enum",
                                          "from app.services.capability.manifest")) for ln in imports))
    ck("no model file / CDN / fetch / camera API reference in the policy source",
       not any(s in src for s in ("mediapipe", "tensorflow", ".tflite", ".onnx", "cdn.", "http://", "https://",
                                  "fetch(", "getUserMedia", "cv2", "urlopen")))

    # ── router: GET /gesture/capabilities is owner-only + dormant with KAI_HOLDING_COMMAND_ENABLED ─
    rsrc = (Path(__file__).resolve().parents[2] / "routers" / "admin_holding_command.py").read_text()
    ck("router exposes GET /gesture/capabilities from GestureSessionPolicy.capabilities() (no second truth)",
       '@router.get("/gesture/capabilities")' in rsrc and "GestureSessionPolicy.capabilities(" in rsrc)
    ck("the whole router is owner-only (dependencies=[Depends(require_kai_ultra)])",
       "dependencies=[Depends(require_kai_ultra)]" in rsrc)
    msrc = (Path(__file__).resolve().parents[2] / "main.py").read_text()
    ck("router is mounted ONLY under KAI_HOLDING_COMMAND_ENABLED (dormant: route absent when off)",
       'KAI_HOLDING_COMMAND_ENABLED' in msrc and "admin_holding_command" in msrc
       and msrc.index('KAI_HOLDING_COMMAND_ENABLED') < msrc.index("from app.routers import admin_holding_command"))

    n = len(res); ok = sum(res)
    print(f"\nGESTURE + CAMERA POLICY (§8/§94) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
