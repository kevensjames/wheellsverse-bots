"""§135 voice cert tests (subset, runnable) for the Phase 7a Voice Command Center backend.
Zero-framework — mirrors test_approval_dialog.py / test_omnipresence_phase5.py. Run (from backend/):
    python3 -m app.services.holding.test_voice_session
or:
    python3 backend/app/services/holding/test_voice_session.py

Covers: permission-denied / mic-unavailable / PTT start-stop / provider-timeout / transcription-fail /
barge-in / mute / session-expiry / duplicate-message / unauthorized-user /
ambiguous-consequential-approval-refused / stop — and asserts NO covert recording path and that
core.wake_word_listener is never imported or invoked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding.voice_session import (   # noqa: E402
    VoiceSessionManager, VoiceSettings, VoicePrivacyMode, VoiceAdapters, QuietMode,
    DEFAULT_PRIVACY_MODE, local_wake_word_status, default_command_api)
from app.services.holding.command_router import CommandContext   # noqa: E402
from app.services.holding.approval_dialog import ConfirmationStatus   # noqa: E402


class _P:
    """A minimal session principal (mirrors capability.risk.Principal's shape used here)."""
    def __init__(self, role="owner", pid="kai-owner"):
        self.role = role
        self.id = pid


class _CloudWake:
    engine_name = "cloud-asr"
    def is_local(self): return False    # a cloud recognizer — must NEVER be an acceptable fallback
    def available(self): return True


class _LocalWake:
    engine_name = "openWakeWord-local"
    def is_local(self): return True
    def available(self): return True


def _mgr(**kw):
    kw.setdefault("enabled", True)          # tests exercise behavior with the flag ON explicitly
    kw.setdefault("is_owner", lambda p: getattr(p, "role", None) == "owner")
    return VoiceSessionManager(**kw)


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    OWNER = _P("owner")

    # ── config: KAI_VOICE_ENABLED defaults False; a manager with no override reads that (VOICE_DISABLED) ──
    from app.config import settings as cfg
    ck("KAI_VOICE_ENABLED default is False", getattr(cfg, "KAI_VOICE_ENABLED", None) is False)
    off = VoiceSessionManager()   # no enabled override → reads the (False) flag
    ck("flag off → every turn is VOICE_DISABLED (nothing runs by default)",
       off.handle_turn("what is deployed", OWNER).status == "VOICE_DISABLED")

    # ── §6: default privacy mode is PUSH_TO_TALK ──────────────────────────────────────────────────
    ck("default privacy mode is PUSH_TO_TALK", VoiceSettings().privacy_mode == VoicePrivacyMode.PUSH_TO_TALK
       and DEFAULT_PRIVACY_MODE == VoicePrivacyMode.PUSH_TO_TALK)

    # ── WAKE_WORD_LOCAL is UNAVAILABLE without a genuinely local engine; cloud is NOT a fallback ────
    ck("wake-word: no engine → UNAVAILABLE", local_wake_word_status(None)["status"] == "UNAVAILABLE")
    ck("wake-word: a CLOUD engine → still UNAVAILABLE (no cloud continuous-audio fallback)",
       local_wake_word_status(_CloudWake())["status"] == "UNAVAILABLE"
       and local_wake_word_status(_CloudWake())["is_local"] is False)
    ck("wake-word: a genuinely LOCAL engine → AVAILABLE (the seam works, honestly gated)",
       local_wake_word_status(_LocalWake())["status"] == "AVAILABLE")
    m_ww = _mgr(settings=VoiceSettings(privacy_mode=VoicePrivacyMode.WAKE_WORD_LOCAL),
                adapters=VoiceAdapters(wake_detector=_CloudWake()))
    r_ww = m_ww.handle_turn("hey kai what changed", OWNER)
    ck("WAKE_WORD_LOCAL mode + cloud engine → turn refused WAKE_WORD_UNAVAILABLE (no covert cloud stream)",
       r_ww.status == "WAKE_WORD_UNAVAILABLE" and r_ww.speak is False)

    # ── permission-denied / unauthorized-user / session-expiry (all §75) ───────────────────────────
    calls = {"n": 0}
    def counting_api(cmd, ctx, *, interaction_mode="voice", environment="production"):
        calls["n"] += 1
        return {"status": "OK", "intent": "QUERY_KNOWLEDGE", "answer": "SOL is on Railway."}

    m = _mgr(command_api=counting_api)
    r = m.handle_turn("what is deployed", _P("operator"), correlation_id="c-denied")
    ck("permission-denied: a non-owner (operator) → UNAUTHORIZED, no routing, no speech",
       r.status == "UNAUTHORIZED" and r.speak is False and calls["n"] == 0)
    ck("permission-denied: a non-owner's WORDS are NOT persisted (final_command empty)",
       r.audit.get("final_command") == "")

    r = m.handle_turn("what is deployed", None, correlation_id="c-expired")
    ck("session-expiry: principal None → UNAUTHORIZED (voice never bypasses auth)",
       r.status == "UNAUTHORIZED" and calls["n"] == 0)

    r = m.handle_turn("what is deployed", _P("viewer"), correlation_id="c-unauth")
    ck("unauthorized-user: a viewer role → UNAUTHORIZED", r.status == "UNAUTHORIZED" and calls["n"] == 0)

    # ── PTT start-stop: a final transcript routes through the command API; audit holds text not audio ──
    r = m.handle_turn("what is deployed", OWNER, correlation_id="c-ptt")
    ck("PTT: final transcript routed through the command API (dispatcher called once)", calls["n"] == 1)
    ck("PTT: owner gets a spoken answer (summary-first) + full display text",
       r.status == "OK" and r.speak is True and r.display_text == "SOL is on Railway."
       and r.spoken_text == "SOL is on Railway.")
    ck("PTT/§92 audit persists ONLY the FINAL command text + response + refs + corr + ts",
       r.audit.get("final_command") == "what is deployed"
       and r.audit.get("final_response") == "SOL is on Railway."
       and r.audit.get("correlation_id") == "c-ptt" and bool(r.audit.get("ts"))
       and r.audit.get("interaction_mode") == "voice")

    # ── §92: the audit record NEVER carries raw audio / bytes under any key ─────────────────────────
    allowed = {"correlation_id", "ts", "final_command", "final_response", "status", "intent",
               "proposal_ref", "result_ref", "mission_id", "interaction_mode", "privacy_mode", "provenance"}
    ck("§92 audit keys are exactly the allowed final-text+refs set (no audio/raw/pcm/wav field)",
       set(r.audit.keys()) == allowed
       and not any(k in r.audit for k in ("audio", "raw", "pcm", "wav", "waveform", "samples")))
    # handle_turn takes a text transcript — there is no audio-bytes parameter anywhere.
    import inspect
    params = set(inspect.signature(VoiceSessionManager.handle_turn).parameters)
    ck("handle_turn accepts TEXT (transcript) only — no audio/bytes parameter",
       "transcript" in params and not (params & {"audio", "audio_bytes", "pcm", "wav", "samples"}))

    # ── transcription-fail: an empty final transcript → EMPTY, nothing routed ──────────────────────
    before = calls["n"]
    r = m.handle_turn("   ", OWNER, correlation_id="c-empty")
    ck("transcription-fail: empty/garbled transcript → EMPTY, no routing",
       r.status == "EMPTY" and calls["n"] == before)

    # interim transcripts are never acted on / persisted (§92)
    r = m.handle_turn("what is dep", OWNER, is_final=False, correlation_id="c-interim")
    ck("interim (non-final) transcript → IGNORED_INTERIM, not routed, not persisted",
       r.status == "IGNORED_INTERIM" and r.speak is False and calls["n"] == before)

    # ── mic-unavailable: transcription adapter reports UNAVAILABLE (capabilities are honest) ────────
    m_mic = _mgr(adapters=VoiceAdapters(transcription=lambda: {"status": "UNAVAILABLE"}))
    ck("mic-unavailable: capabilities report transcription UNAVAILABLE honestly",
       m_mic.capabilities()["transcription"]["status"] == "UNAVAILABLE")

    # ── provider-timeout: the command API raises → SYSTEM_DEGRADED, no crash, no speech ────────────
    def boom_api(cmd, ctx, *, interaction_mode="voice", environment="production"):
        raise TimeoutError("provider timed out")
    m_to = _mgr(command_api=boom_api)
    r = m_to.handle_turn("what is deployed", OWNER, correlation_id="c-timeout")
    ck("provider-timeout: routing failure → SYSTEM_DEGRADED (honest), nothing spoken",
       r.status == "SYSTEM_DEGRADED" and r.speak is False)

    # a soft TIMEOUT status is passed through honestly (no fabricated answer)
    m_ts = _mgr(command_api=lambda *a, **k: {"status": "TIMEOUT", "intent": ""})
    r = m_ts.handle_turn("what is deployed", OWNER, correlation_id="c-timeout2")
    ck("provider soft-timeout status passed through (no fabricated answer)",
       r.status == "TIMEOUT" and r.display_text == "")

    # ── barge-in / stop: exactly ONE cancellation path (kai-barge-in.js), backend only relays it ───
    b = _mgr().barge_in()
    ck("barge-in relays the ONE controller (single_path) and stops", b["single_path"] is True and b["stopped"] is True)
    s = _mgr().stop()
    ck("stop uses the same single cancellation path", s["single_path"] is True and s["reason"] == "user-stop")

    # ── mute (§68): hard mute → MUTED, nothing routed, no words persisted ──────────────────────────
    calls2 = {"n": 0}
    def api2(cmd, ctx, *, interaction_mode="voice", environment="production"):
        calls2["n"] += 1; return {"status": "OK", "answer": "x"}
    m_mute = _mgr(command_api=api2, quiet=QuietMode(muted=True))
    r = m_mute.handle_turn("what is deployed", OWNER, correlation_id="c-mute")
    ck("mute: muted → MUTED, no routing, no speech", r.status == "MUTED" and r.speak is False and calls2["n"] == 0)

    # ── duplicate-message: a repeated correlation_id is idempotent (no re-route, no re-persist) ─────
    calls3 = {"n": 0}
    def api3(cmd, ctx, *, interaction_mode="voice", environment="production"):
        calls3["n"] += 1; return {"status": "OK", "answer": "once"}
    m_dup = _mgr(command_api=api3)
    r1 = m_dup.handle_turn("what is deployed", OWNER, correlation_id="dup-1")
    r2 = m_dup.handle_turn("what is deployed", OWNER, correlation_id="dup-1")
    ck("duplicate-message: same correlation_id handled once → 2nd is DUPLICATE (idempotent)",
       r1.status == "OK" and r2.status == "DUPLICATE" and calls3["n"] == 1)

    # ── ambiguous-consequential-approval-refused (§24/§75/§128-130) ────────────────────────────────
    # A consequential command routes through the SAME §8 resolver → REQUIRE_APPROVAL; voice can't run it.
    m_c = _mgr()   # default_command_api routes through command_router.resolve (the command API's core)
    r = m_c.handle_turn("deploy sol to production", OWNER, correlation_id="c-conseq")
    ck("consequential voice command → REQUIRE_APPROVAL, NOT executed (routed via the command API)",
       r.status == "REQUIRE_APPROVAL" and r.speak in (True, False))
    ck("REQUIRE_APPROVAL reply tells the owner voice can't authorize it",
       "can't authorize" in r.display_text.lower())

    # An ambiguous 'ok'/'do it' over VOICE never authorizes; even a perfectly-worded 'approve 42' is refused.
    dec1 = m_c.confirm_by_voice("42", "ok do it", OWNER)
    ck("ambiguous 'ok do it' over voice → NOT authorized (§75)", dec1["authorized"] is False)
    dec2 = m_c.confirm_by_voice("42", "approve 42", OWNER)
    ck("even explicit 'approve 42' over VOICE → REFUSED_CHANNEL, no authority (§75/§128-130)",
       dec2["authorized"] is False and dec2["status"] == ConfirmationStatus.REFUSED_CHANNEL.value)

    # ── the command API is a CLASSIFIER, never a shell/eval (routes through resolve) ────────────────
    out = default_command_api("delete the production database", CommandContext())
    ck("voice routes THROUGH the command API resolver → consequential fails closed to REQUIRE_APPROVAL",
       out["status"] == "REQUIRE_APPROVAL")
    out = default_command_api("what is deployed", CommandContext())
    ck("voice read query routes to the read-only knowledge index (no fabricated answer)",
       out["status"] == "ROUTED_KNOWLEDGE" and out["answer"] == "")

    # ── NO covert recording path: core.wake_word_listener is never imported or invoked ─────────────
    ck("core.wake_word_listener is NOT imported by exercising the voice manager",
       "core.wake_word_listener" not in sys.modules)
    src = (Path(__file__).resolve().parent / "voice_session.py").read_text()
    import_hit = any("wake_word_listener" in ln and "import" in ln for ln in src.splitlines())
    call_hit = any(sym in src for sym in ("start_listener(", "get_listener(", "stop_listener(",
                                          "WakeWordListener("))
    ck("voice_session.py never IMPORTS or INVOKES the covert wake_word_listener (mentions in docs only)",
       not import_hit and not call_hit)
    ck("voice_session.py never calls a cloud recognizer / continuous mic loop (no recognize_google / Microphone)",
       "recognize_google" not in src and "Microphone" not in src and "pyaudio" not in src)

    n = len(res); ok = sum(res)
    print(f"\nVOICE COMMAND CENTER (§135) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
