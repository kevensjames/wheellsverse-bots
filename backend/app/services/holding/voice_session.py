"""§7 Voice Command Center (BACKEND) — VoiceSessionManager. Phase 7a.

Assembles the operator-speaks → transcript → identity/session → Holding Command API → response →
optional action proposal → speech loop by REUSING the certified-but-dormant adapters. It does NOT
rebuild them and it introduces NO second voice pipeline (no voice_v2):

  - kai-speech-input.js  (SpeechActivityDetector + TranscriptionAdapter) — runs in the BROWSER. The
    backend receives ONLY the FINAL transcript TEXT; raw ambient audio never leaves the browser and
    never reaches this process (§92 ephemeral audio).
  - kai-tts-provider.js  (SpeechResponseAdapter) — the browser speaks. The backend only decides
    IF/WHAT to speak (summary-first + auto-speak-critical, §51).
  - kai-barge-in.js      (the ONE KaiSpeechCancellationController) — the single cancellation path.
    The backend only SIGNALS it; it never implements a divergent stop (§52).

SECURITY / PRIVACY (this is the whole point of the phase):
  - §6 privacy modes: VOICE_OFF / PUSH_TO_TALK (DEFAULT) / WAKE_WORD_LOCAL / SESSION_LISTENING.
    WAKE_WORD_LOCAL is honestly UNAVAILABLE unless a GENUINELY on-device vetted engine is present —
    it NEVER streams continuous ambient audio to a cloud recognizer (cloud is not an acceptable
    fallback). The covert core/wake_word_listener.py (the always-on NarAI mic that ships audio to
    Google) is DISABLED here and is NEVER imported or invoked by this module.
  - §75/§128-130: a voice-channel confirmation NEVER authorizes a consequential action. confirm_by_voice
    delegates to the EXISTING approval_dialog.authorize(channel="voice"), which REFUSES the voice
    channel — no durable write, ever. Voice never bypasses auth; the session principal is authoritative.
  - §92 audit: persist ONLY the final recognized command + KAI's final response + proposal/result refs
    + correlation_id + ts. Raw audio is never persisted, never logged, never in URLs. Only FINAL
    transcripts are acted on/persisted — interim is dropped.
  - §67 settings + §68 quiet mode as typed, privacy-preserving config.

Flag: KAI_VOICE_ENABLED (config.py) default False — nothing runs live by default. Pure/injectable:
the whole manager is DB-free and testable as a plain python3 script (test_voice_session.py).
"""
from __future__ import annotations

import uuid as _uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from app.services.holding.approval_dialog import ConfirmationStatus, authorize as _approval_authorize
from app.services.holding.command_router import CommandContext, Dispatch, Intent, resolve
from app.services.holding.task_resolver import redact

# §51 summary-first: TTS says a short summary; full depth stays on the dashboard.
_SPOKEN_SUMMARY_MAX = 350
# Severities that may auto-speak through quiet hours (only when auto_speak_critical is on).
_CRITICAL = frozenset({"critical", "sev1", "sev-1", "p0"})


# ── §6 privacy modes ──────────────────────────────────────────────────────────────────────────────
class VoicePrivacyMode(str, Enum):
    VOICE_OFF = "VOICE_OFF"                  # no voice in/out
    PUSH_TO_TALK = "PUSH_TO_TALK"            # DEFAULT — mic only while the operator holds the control
    WAKE_WORD_LOCAL = "WAKE_WORD_LOCAL"      # on-device wake word ONLY; UNAVAILABLE without a local engine
    SESSION_LISTENING = "SESSION_LISTENING"  # explicit, indicator-on listening session


DEFAULT_PRIVACY_MODE = VoicePrivacyMode.PUSH_TO_TALK


# ── §67 presence/voice settings (privacy-preserving defaults) ───────────────────────────────────────
@dataclass
class VoiceSettings:
    privacy_mode: VoicePrivacyMode = DEFAULT_PRIVACY_MODE
    greeting: str = ""            # "" = no auto-greeting (privacy-preserving)
    voice_name: str = ""          # "" = provider default; the masculine pick lives in kai-tts-provider.js
    speed: float = 1.0
    auto_speak_critical: bool = True    # ONLY critical severity auto-speaks; everything else is text-first
    wake_word_enabled: bool = False     # even in WAKE_WORD_LOCAL this requires a genuinely local engine
    mic_indicator_required: bool = True  # a visible mic/recording indicator is MANDATORY — never covert (§6)
    quiet_hours: Optional[tuple] = None  # (start_hour_utc, end_hour_utc) or None

    def __post_init__(self):
        if not isinstance(self.privacy_mode, VoicePrivacyMode):
            self.privacy_mode = VoicePrivacyMode(str(self.privacy_mode))
        self.speed = max(0.5, min(2.0, float(self.speed)))


# ── §68 quiet mode state ────────────────────────────────────────────────────────────────────────────
@dataclass
class QuietMode:
    """muted = hard input mute (mic off, nothing processed, nothing spoken). quiet_hours suppress
    non-critical SPOKEN output (text is still returned for the dashboard)."""
    muted: bool = False

    def within_quiet_hours(self, settings: VoiceSettings, now: datetime) -> bool:
        qh = settings.quiet_hours
        if not qh:
            return False
        try:
            start, end = int(qh[0]), int(qh[1])
        except Exception:
            return False
        h = now.hour
        return (start <= h < end) if start <= end else (h >= start or h < end)


# ── on-device wake-word seam (honestly UNAVAILABLE without a genuinely local engine) ─────────────────
def local_wake_word_status(detector=None) -> dict:
    """Honest availability for on-device wake-word detection. Returns UNAVAILABLE unless a genuinely
    LOCAL, vetted engine is injected and ready. A non-local (cloud) engine is NEVER an acceptable
    fallback for continuous listening — it stays UNAVAILABLE. This never touches
    core.wake_word_listener (the covert always-on NarAI mic)."""
    if detector is None:
        return {"status": "UNAVAILABLE", "available": False, "engine": None, "is_local": False,
                "reason": "no on-device wake-word engine present — cloud continuous-audio fallback is forbidden (§6)"}
    try:
        is_local = bool(detector.is_local())
        avail = bool(detector.available())
    except Exception:
        return {"status": "UNAVAILABLE", "available": False, "engine": None, "is_local": False,
                "reason": "wake-word detector seam errored — fail closed to UNAVAILABLE"}
    engine = getattr(detector, "engine_name", None)
    if not is_local:
        return {"status": "UNAVAILABLE", "available": False, "engine": engine, "is_local": False,
                "reason": "detector is not on-device — refusing cloud continuous-audio fallback (§6)"}
    if not avail:
        return {"status": "UNAVAILABLE", "available": False, "engine": engine, "is_local": True,
                "reason": "local wake-word engine present but not ready"}
    return {"status": "AVAILABLE", "available": True, "engine": engine, "is_local": True, "reason": ""}


# ── the certified BROWSER adapters, as backend seams (assemble, don't rebuild) ──────────────────────
@dataclass
class VoiceAdapters:
    # transcription capability truth (mirrors kai-speech-input.js getCapabilities); backend gets TEXT only
    transcription: Callable[[], dict] = field(default=lambda: {
        "status": "BROWSER_LIMITED",
        "note": "Web Speech recognition is Chrome/webkit-only, permission-gated, often network-backed"})
    # response capability truth (mirrors kai-tts-provider.js); no viseme timestamps from Web Speech
    response: Callable[[], dict] = field(default=lambda: {"status": "BROWSER", "viseme_timestamps": False})
    # the ONE cancellation controller (kai-barge-in.js) — backend only relays the single-path signal
    barge_in: Callable[[], dict] = field(default=lambda: {"stopped": True, "reason": "barge-in"})
    wake_detector: object = None   # on-device wake-word engine seam (default None → UNAVAILABLE)


# ── the result of one voice turn ────────────────────────────────────────────────────────────────────
@dataclass
class VoiceTurnResult:
    status: str
    speak: bool = False
    spoken_text: str = ""       # summary-first (≤ _SPOKEN_SUMMARY_MAX) — what TTS actually says
    display_text: str = ""      # full text for the dashboard (§51 depth-on-dashboard)
    intent: str = ""
    correlation_id: str = ""
    proposal_ref: str = ""
    result_ref: str = ""
    mission_id: str = ""
    privacy_mode: str = ""
    reason: str = ""
    audit: dict = field(default_factory=dict)
    provenance: str = "REAL"

    def as_dict(self) -> dict:
        return asdict(self)


# ── default command-API adapter: route the TYPED command through the SAME §8 resolver ───────────────
def default_command_api(command: str, context: CommandContext, *, interaction_mode: str = "voice",
                        environment: str = "production") -> dict:
    """Classify a voice command with the SAME §8 resolver the Holding Command API uses (never exec'd).
    This DEFAULT does classification + the consequential fail-closed check only — it does NOT run the
    Brain/knowledge dispatch (that needs the seeded registry / DB). Production wiring injects a
    command_api that delegates to admin_holding_command's dispatch for real read answers. Honest by
    construction: it never fabricates an answer."""
    res = resolve(command, context, environment=environment)
    if res.intent == Intent.CONSEQUENTIAL.value:
        return {"status": "REQUIRE_APPROVAL", "intent": res.intent, "action_class": res.action_class,
                "approval": res.approval, "injection_flags": res.injection_flags}
    if res.dispatch == Dispatch.KNOWLEDGE.value:
        return {"status": "ROUTED_KNOWLEDGE", "intent": res.intent, "answer": "",
                "note": "routed to the read-only knowledge index (inject a dispatcher for the answer)",
                "injection_flags": res.injection_flags}
    if res.dispatch == Dispatch.BRAIN.value:
        return {"status": "ROUTED_BRAIN", "intent": res.intent, "answer": "",
                "note": "routed to the Brain (read-only V1; execution gated by brake #1)",
                "injection_flags": res.injection_flags}
    return {"status": "UNKNOWN", "intent": res.intent, "answer": "",
            "note": "not an authorized holding intent — nothing ran", "injection_flags": res.injection_flags}


def _default_audit_sink(rec: dict) -> None:
    """Durable §92 voice audit → App B AuditLog (fail-open). Only final text + refs, never audio (§92)."""
    try:
        from app.database import SessionLocal
        from app.models.admin import AuditLog
        s = SessionLocal()
        try:
            s.add(AuditLog(action="holding.voice.turn", actor_type="owner", event_metadata=rec))
            s.commit()
        finally:
            s.close()
    except Exception:
        pass


class VoiceSessionManager:
    """§7 orchestration for one voice turn. Enforces §6 privacy modes, §68 quiet/mute, §75 session
    authority + voice-never-authorizes, §92 audit (final text only), and the §51 speech decision —
    then delegates routing to the command API and cancellation to the one barge-in controller."""

    def __init__(self, *, settings: VoiceSettings | None = None, quiet: QuietMode | None = None,
                 adapters: VoiceAdapters | None = None,
                 command_api: Callable[..., dict] | None = None,
                 audit_sink: Callable[[dict], None] | None = None,
                 is_owner: Callable[[object], bool] | None = None,
                 enabled: bool | None = None, environment: str = "production",
                 now: Callable[[], datetime] | None = None):
        self.settings = settings or VoiceSettings()
        self.quiet = quiet or QuietMode()
        self.adapters = adapters or VoiceAdapters()
        self._command_api = command_api or default_command_api
        self._audit = audit_sink or _default_audit_sink
        self._is_owner = is_owner or (lambda p: getattr(p, "role", None) == "owner")
        self._enabled_override = enabled
        self.environment = environment
        self._now = now or (lambda: datetime.now(timezone.utc))
        # ponytail: in-proc idempotency dedup, bounded; swap for a shared idempotency store if multi-worker.
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()

    # ── config-gated master flag (§ KAI_VOICE_ENABLED, default False) ───────────────────────────────
    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        try:
            from app.config import settings as cfg
            return bool(getattr(cfg, "KAI_VOICE_ENABLED", False))
        except Exception:
            return False

    def wake_word_availability(self) -> dict:
        return local_wake_word_status(self.adapters.wake_detector)

    def capabilities(self) -> dict:
        return {
            "enabled": self.enabled,
            "privacy_mode": self.settings.privacy_mode.value,
            "default_privacy_mode": DEFAULT_PRIVACY_MODE.value,
            "muted": self.quiet.muted,
            "mic_indicator_required": self.settings.mic_indicator_required,
            "transcription": self.adapters.transcription(),
            "response": self.adapters.response(),
            "wake_word": self.wake_word_availability(),
        }

    # ── the single cancellation path (§52) — relay to kai-barge-in.js, never a second stop ──────────
    def barge_in(self, reason: str = "barge-in") -> dict:
        out = dict(self.adapters.barge_in() or {})
        out["reason"] = reason      # the relay label for THIS stop (barge-in vs user-stop)
        out["single_path"] = True   # there is exactly ONE cancellation controller
        return out

    def stop(self, reason: str = "user-stop") -> dict:
        return self.barge_in(reason)

    # ── §92 durable audit — ONLY final text + refs, NEVER raw audio ─────────────────────────────────
    def _persist(self, corr, command_text, response_text, status, intent,
                 proposal_ref, result_ref, mission_id) -> dict:
        rec = {
            "correlation_id": corr,
            "ts": self._now().isoformat(),
            "final_command": redact((command_text or "")[:2000]),
            "final_response": redact((response_text or "")[:2000]),
            "status": status,
            "intent": intent,
            "proposal_ref": proposal_ref,
            "result_ref": result_ref,
            "mission_id": mission_id,
            "interaction_mode": "voice",
            "privacy_mode": self.settings.privacy_mode.value,
            "provenance": "REAL",
        }
        # §92: raw ambient audio is never an input here and is never persisted — only final text + refs.
        try:
            self._audit(dict(rec))
        except Exception:
            pass
        return rec

    def _should_speak(self, severity) -> bool:
        if self.settings.privacy_mode == VoicePrivacyMode.VOICE_OFF:
            return False
        if self.quiet.within_quiet_hours(self.settings, self._now()):
            return bool(str(severity).lower() in _CRITICAL and self.settings.auto_speak_critical)
        return True

    def _summarize(self, text: str) -> str:
        t = (text or "").strip()
        if len(t) <= _SPOKEN_SUMMARY_MAX:
            return t
        return t[:_SPOKEN_SUMMARY_MAX].rsplit(" ", 1)[0] + "…"

    @staticmethod
    def _describe_approval(pkg: dict) -> str:
        if not pkg:
            return "A consequential action is pending your approval."
        act = pkg.get("ACTION") or pkg.get("action") or "?"
        tgt = pkg.get("TARGET") or pkg.get("target") or "?"
        risk = pkg.get("RISK") or pkg.get("action_class") or pkg.get("risk") or "?"
        conf = pkg.get("required_confirmation") or "approve <id>"
        return f"ACTION {act} · TARGET {tgt} · RISK {risk}. Type '{conf}' to authorize (voice can't)."

    def _mark(self, corr: str) -> None:
        self._seen.add(corr)
        self._seen_order.append(corr)
        if len(self._seen_order) > 256:
            self._seen.discard(self._seen_order.popleft())

    # ── one voice turn ──────────────────────────────────────────────────────────────────────────────
    def handle_turn(self, transcript: str, principal, *, is_final: bool = True, severity: str = "info",
                    correlation_id: str | None = None,
                    context: CommandContext | None = None) -> VoiceTurnResult:
        corr = correlation_id or _uuid.uuid4().hex
        mode = self.settings.privacy_mode
        pm = mode.value

        # duplicate-message: an already-handled correlation id is idempotent — no re-route, no re-persist.
        if corr in self._seen:
            return VoiceTurnResult(status="DUPLICATE", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="duplicate correlation_id — already handled (idempotent)")
        self._mark(corr)

        # 1. master flag off → nothing runs (default posture)
        if not self.enabled:
            return VoiceTurnResult(status="VOICE_DISABLED", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="KAI_VOICE_ENABLED is off — voice never runs by default")
        # 2. privacy mode VOICE_OFF
        if mode == VoicePrivacyMode.VOICE_OFF:
            return VoiceTurnResult(status="VOICE_OFF", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="voice disabled by privacy mode")
        # 3. §68 hard mute — mic off, nothing processed, nothing spoken (no routing, no persist of words)
        if self.quiet.muted:
            return VoiceTurnResult(status="MUTED", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="muted (§68) — mic off, no processing")
        # 4. WAKE_WORD_LOCAL requires a genuinely local engine — never a cloud continuous-audio fallback
        if mode == VoicePrivacyMode.WAKE_WORD_LOCAL:
            wa = self.wake_word_availability()
            if not wa["available"]:
                return VoiceTurnResult(status="WAKE_WORD_UNAVAILABLE", speak=False, correlation_id=corr,
                                       privacy_mode=pm, reason=wa["reason"])
        # 5. §75 session-principal authority — voice never bypasses auth. Do NOT persist a non-owner's words.
        if not self._is_owner(principal):
            audit = self._persist(corr, "", "", "UNAUTHORIZED", "", "", "", "")
            return VoiceTurnResult(status="UNAUTHORIZED", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="voice does not bypass auth — an owner session is required (§75)",
                                   audit=audit)
        # 6. §92 only FINAL transcripts are acted on / persisted — interim audio↦text is ephemeral
        if not is_final:
            return VoiceTurnResult(status="IGNORED_INTERIM", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="interim transcript — not routed, not persisted (§92)")
        text = (transcript or "").strip()
        if not text:
            return VoiceTurnResult(status="EMPTY", speak=False, correlation_id=corr, privacy_mode=pm,
                                   reason="empty final transcript (mic/transcription produced nothing)")

        ctx = context or CommandContext()
        mission_id = ctx.selected_mission or ""

        # route THROUGH the command API (shared §8 resolver). Provider failure → honest degraded, no crash.
        try:
            out = self._command_api(text, ctx, interaction_mode="voice", environment=self.environment) or {}
        except Exception:
            audit = self._persist(corr, text, "", "SYSTEM_DEGRADED", "", "", "", mission_id)
            return VoiceTurnResult(status="SYSTEM_DEGRADED", speak=False, correlation_id=corr, privacy_mode=pm,
                                   mission_id=mission_id, audit=audit,
                                   reason="command routing failed — degraded, nothing spoken")

        status = out.get("status", "UNKNOWN")
        intent = out.get("intent", "")

        # §24/§75/§128-130: consequential → approval required; voice CANNOT authorize it here.
        if status == "REQUIRE_APPROVAL":
            pkg = out.get("approval") or {}
            proposal_ref = str(pkg.get("pending_action_id") or pkg.get("target") or "")
            display = "This needs your explicit approval and voice can't authorize it. " + self._describe_approval(pkg)
            spoken = "This needs your explicit approval. I can't authorize it by voice."
            speak = self._should_speak(severity)
            audit = self._persist(corr, text, spoken, status, intent, proposal_ref, "", mission_id)
            return VoiceTurnResult(status="REQUIRE_APPROVAL", speak=speak,
                                   spoken_text=spoken if speak else "", display_text=display, intent=intent,
                                   correlation_id=corr, proposal_ref=proposal_ref, mission_id=mission_id,
                                   privacy_mode=pm, audit=audit,
                                   reason="consequential — owner approval required; voice carries no authority (§75/§128-130)")

        # non-consequential (read/capability/degraded/unknown) — return the answer, decide speech.
        answer = out.get("answer") or out.get("note") or ""
        display = str(answer)
        spoken = self._summarize(display)
        speak = self._should_speak(severity) and bool(display)
        result_ref = str(out.get("result_ref") or "")
        audit = self._persist(corr, text, spoken or display, status, intent, "", result_ref, mission_id)
        return VoiceTurnResult(status=status, speak=speak, spoken_text=spoken if speak else "",
                               display_text=display, intent=intent, correlation_id=corr,
                               result_ref=result_ref, mission_id=mission_id, privacy_mode=pm, audit=audit,
                               reason="routed through the command API")

    # ── §75/§128-130: a voice confirmation NEVER authorizes a consequential action ──────────────────
    def confirm_by_voice(self, pending_action_id, reply: str, principal, *,
                         correlation_id: str | None = None) -> dict:
        """Delegates to the EXISTING approval_dialog.authorize(channel="voice"), which REFUSES the voice
        channel — no durable write, ever, regardless of how perfectly worded the reply is. This is the
        single authorization authority; the voice channel adds none."""
        corr = correlation_id or _uuid.uuid4().hex
        owner = getattr(principal, "id", "") or "owner"
        out = _approval_authorize(pending_action_id, principal=owner, utterance=reply, channel="voice")
        dec = out.get("decision", {}) or {}
        self._persist(corr, reply, "voice cannot authorize — REFUSED_CHANNEL", "APPROVAL_REFUSED_VOICE",
                      "CONSEQUENTIAL", str(pending_action_id), "", "")
        return {"authorized": bool(out.get("authorized")),   # always False for the voice channel
                "status": dec.get("status", ConfirmationStatus.REFUSED_CHANNEL.value),
                "reason": out.get("reason", "voice carries no authority (§75)"),
                "correlation_id": corr, "record": out.get("record")}


if __name__ == "__main__":
    from app.services.holding.test_voice_session import run
    raise SystemExit(0 if run() else 1)
