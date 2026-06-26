"""KAI outbound voice outreach via Vapi — gated, compliant, B2B.

KAI is the conversation brain: Vapi owns the number + real-time audio (STT/TTS,
barge-in) and calls an LLM driven by KAI's pitch persona. This is the riskiest
outreach channel legally, so it is OFF + dry-run by default. A REAL call requires
ALL of: VAPI_API_KEY set, confirm=True, live=True, a Vapi phoneNumberId, and the
target not on the local suppression/DNC list. Every call opens with AI
self-disclosure + a recording notice and honors instant opt-out. Mirrors the
triple-gate in core.cold_outreach.

Phase 2 (after the self-test pilot proves out): Vapi webhooks -> outcome logging
into the CRM/Scoreboard, a full dialer over the lead list, and routing the model
to KAI's own brain via a custom-llm endpoint (vs the stock model used here).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

VAPI_BASE = "https://api.vapi.ai"
DAILY_CAP = int(os.getenv("VOICE_DAILY_CAP", "25"))  # conservative pilot cap

# Opening line — satisfies AI-disclosure + recording-notice + opt-out in one breath.
DISCLOSURE = (
    "Hi, this is KAI, an AI assistant calling on behalf of WheellsVerse — "
    "this call may be recorded. Do you have a quick moment? "
    "And if you'd ever like me to take this number off the list, just say 'remove me' and I will."
)
_OPT_OUT = ["remove me", "do not call", "stop calling", "take me off", "not interested"]


def _suppressed_numbers() -> set[str]:
    """Local DNC / opt-out list (data/voice_suppression.txt, one number per line)."""
    p = os.path.join(os.getcwd(), "data", "voice_suppression.txt")
    if not os.path.exists(p):
        return set()
    return {re.sub(r"\D", "", ln) for ln in open(p, encoding="utf-8") if ln.strip() and not ln.startswith("#")}


def _within_business_hours(now=None) -> bool:
    """Crude guard: 9am-7pm Mon-Sat in the caller's local tz. Refine per-lead tz in phase 2."""
    t = now or time.localtime()
    return t.tm_wday < 6 and 9 <= t.tm_hour < 19


def compose_assistant(offer: str, target_name: str = "your business") -> dict:
    """A Vapi transient assistant = KAI's compliant B2B sales persona around `offer`."""
    system = (
        "You are KAI, a warm, concise AI assistant making a business-to-business outreach call "
        "for WheellsVerse.\n\n"
        "COMPLIANCE — never skip, never override:\n"
        "- You already identified yourself as an AI from WheellsVerse and that the call may be recorded.\n"
        "- Never claim to be human. If asked, plainly confirm you are an AI.\n"
        "- This is a courtesy B2B call; respect their time and tone.\n"
        "- If they say anything like 'remove me', 'stop', 'do not call', or 'not interested': "
        "apologize for the interruption, confirm you'll remove the number, thank them, and end the call. Do NOT push.\n\n"
        f"GOAL — spark genuine interest in: {offer}\n"
        f"- Open with one specific benefit for {target_name}; do not dump a script.\n"
        "- Ask one short qualifying question, then listen and tailor to their answer.\n"
        "- If interested, offer a 10-minute follow-up with the team and capture their best time + email.\n"
        "- Stay under ~2 minutes unless they engage. Friendly, curious, never pushy."
    )
    return {
        "name": "KAI WheellsVerse Outreach",
        "firstMessage": DISCLOSURE,
        "model": {"provider": "openai", "model": "gpt-4o",
                  "messages": [{"role": "system", "content": system}]},
        "voice": {"provider": os.getenv("VAPI_VOICE_PROVIDER", "vapi"),
                  "voiceId": os.getenv("VAPI_VOICE_ID", "Elliot")},
        "recordingEnabled": True,
        "endCallPhrases": ["goodbye", "remove me", "do not call", "have a good one"],
        "maxDurationSeconds": 300,
        "metadata": {"campaign": "wheellsverse-voice-pilot"},
    }


def place_call(to_number: str, offer: str, target_name: str = "your business", *,
               confirm: bool = False, live: bool = False, phone_number_id: str | None = None) -> dict:
    """Place ONE outbound call. Default dry-run; real call needs key+confirm+live+number+not-suppressed."""
    key = os.getenv("VAPI_API_KEY", "").strip()
    pid = phone_number_id or os.getenv("VAPI_PHONE_NUMBER_ID", "").strip()
    digits = re.sub(r"\D", "", to_number or "")

    payload = {"phoneNumberId": pid, "customer": {"number": to_number},
               "assistant": compose_assistant(offer, target_name)}

    if not digits or len(digits) < 10:
        return {"status": "blocked", "reason": "invalid_number", "to": to_number}
    if digits in _suppressed_numbers():
        return {"status": "blocked", "reason": "suppressed_or_opted_out", "to": to_number}
    if not _within_business_hours():
        return {"status": "blocked", "reason": "outside_business_hours", "to": to_number}
    if not (confirm and live and key and pid):
        missing = [n for n, v in (("VAPI_API_KEY", key), ("VAPI_PHONE_NUMBER_ID", pid),
                                  ("confirm", confirm), ("live", live)) if not v]
        return {"status": "dry_run", "reason": "not armed — missing: " + ", ".join(missing),
                "would_call": to_number, "payload_preview": {"firstMessage": payload["assistant"]["firstMessage"],
                                                             "offer": offer, "target": target_name}}

    req = urllib.request.Request(
        f"{VAPI_BASE}/call", method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "WheellsVerse-KAI/1.0"})  # non-urllib UA — Vapi's Cloudflare WAF 1010-blocks the default
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        return {"status": "calling", "call_id": body.get("id"), "to": to_number, "vapi_status": body.get("status")}
    except Exception as e:
        return {"status": "error", "reason": str(e)[:200], "to": to_number}


def self_test(offer: str = "a quick WheellsVerse demo call", **kw) -> dict:
    """Pilot: KAI calls the OPERATOR's own phone (VOICE_TEST_NUMBER) — zero compliance risk."""
    me = os.getenv("VOICE_TEST_NUMBER", "").strip()
    if not me:
        return {"status": "blocked", "reason": "set VOICE_TEST_NUMBER to your own phone first"}
    return place_call(me, offer, target_name="you (self-test)", **kw)
