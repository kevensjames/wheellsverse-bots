"""OPT-IN briefing delivery — DEFAULT OFF; a deliberate, operator-gated exception to report-only.

The Holding OS is report-only by design. This module can send a SUMMARY of the morning briefing to
the operator's OWN channel (Telegram — the same channel the observability monitor uses), but ONLY
when BOTH are true:
  1. the operator explicitly opted in:  KAI_HOLDING_DELIVERY_ENABLED = true  (default False), AND
  2. the operator configured the channel: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (env, never committed).
With either missing it is a strict NO-OP. Nothing is ever sent autonomously — enabling delivery is a
deliberate operator choice. The token is never logged or returned. Never raises.
"""
from __future__ import annotations
import os
import urllib.error
import urllib.parse
import urllib.request


def _summary(briefing: dict) -> str:
    k = briefing.get("kpis", {}) or {}
    prios = briefing.get("todays_priorities", [])
    lines = [f"KAI Holding briefing — {k.get('as_of', '')}".strip(),
             (f"entities {k.get('entities_total')} · verified {k.get('entities_verified')} · "
              f"risks {k.get('open_risks')} · awaiting-confirm {k.get('fields_awaiting_confirmation')} · "
              f"health {k.get('health')} · caps {k.get('capabilities')}")]
    if isinstance(prios, list):
        lines.append(f"Top priorities ({len(prios)}):")
        for p in prios[:5]:
            lines.append(f"  [{p.get('severity')}] {str(p.get('title', ''))[:80]}")
    lines.append("(report-only summary — KAI took no action)")
    return "\n".join(lines)


def _send_text(text: str) -> dict:
    """Raw Telegram send if a channel is configured. Never raises; never logs/returns the token."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"delivered": False, "reason": "no channel configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset)"}
    try:
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload)
        with urllib.request.urlopen(req, timeout=10) as r:
            return {"delivered": r.status == 200, "channel": "telegram"}
    except urllib.error.HTTPError as e:
        # Telegram encodes WHICH thing is wrong in the status, and the difference is the whole
        # triage. A raw "HTTP Error 404" reads like a transient outage and gets ignored; it is not.
        # kai-briefing-cron produced exactly that on every run for days while holding a bot token
        # that no longer existed — the service was missed when the others were rotated. Naming the
        # cause is the difference between a loop that looks flaky and one that is provably
        # misconfigured.
        cause = {
            404: "bot token invalid or revoked (Telegram 404 means the bot does not exist)",
            401: "bot token unauthorized",
            400: "bad request — chat_id likely wrong or the bot was never started by that chat",
            403: "bot blocked by the chat, or not a member of it",
        }.get(e.code, f"HTTP {e.code}")
        return {"delivered": False, "reason": f"telegram rejected: {cause}",
                "actionable": e.code in (400, 401, 403, 404)}
    except Exception as e:
        return {"delivered": False, "reason": f"send error: {str(e)[:80]}", "actionable": False}


def deliver_briefing(briefing: dict) -> dict:
    """Send the briefing summary IFF opted in AND a channel is configured. Strict no-op otherwise."""
    try:
        from app.config import settings
        if not getattr(settings, "KAI_HOLDING_DELIVERY_ENABLED", False):
            return {"delivered": False, "reason": "delivery disabled (default) — opt in via KAI_HOLDING_DELIVERY_ENABLED"}
        return _send_text(_summary(briefing))
    except Exception as e:
        return {"delivered": False, "reason": f"send error: {str(e)[:80]}"}


def send_alert(text: str) -> dict:
    """Send a proactive watch alert IFF delivery is opted in AND a channel is configured (reuses the
    same owner channel). Strict no-op otherwise. Never raises."""
    try:
        from app.config import settings
        if not getattr(settings, "KAI_HOLDING_DELIVERY_ENABLED", False):
            return {"delivered": False, "reason": "delivery disabled (default)"}
        return _send_text(text)
    except Exception as e:
        return {"delivered": False, "reason": f"send error: {str(e)[:80]}"}


def demo() -> None:
    """Self-check: strict no-op when disabled / unconfigured (no send path exercised)."""
    r = deliver_briefing({"kpis": {"entities_total": 11}, "todays_priorities": []})
    assert r["delivered"] is False and "disabled" in r["reason"], r   # default off
    print("delivery.demo OK — default no-op:", r["reason"])

    # HTTP status -> cause. The reason a 404 was ignored for days is that it read like an outage.
    import urllib.error as _ue

    def _fake(code):
        def _raise(*a, **k):
            raise _ue.HTTPError("https://api.telegram.org/botX/sendMessage", code, "x", None, None)
        return _raise

    _real = urllib.request.urlopen
    os.environ["TELEGRAM_BOT_TOKEN"] = "t"
    os.environ["TELEGRAM_CHAT_ID"] = "c"
    try:
        for code, needle, actionable in ((404, "invalid or revoked", True),
                                         (401, "unauthorized", True),
                                         (400, "chat_id", True),
                                         (403, "blocked", True),
                                         (500, "HTTP 500", False)):
            urllib.request.urlopen = _fake(code)
            r = _send_text("x")
            assert r["delivered"] is False, code
            assert needle in r["reason"], f"{code}: {r['reason']}"
            assert r["actionable"] is actionable, code
        # a missing channel is still a clean no-op, not an "actionable" failure
        os.environ.pop("TELEGRAM_BOT_TOKEN")
        r = _send_text("x")
        assert r["delivered"] is False and "no channel configured" in r["reason"]
    finally:
        urllib.request.urlopen = _real
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    print("delivery.demo OK — 404/401/400/403 classified and marked actionable")


if __name__ == "__main__":
    demo()
