"""Delivery adapters for the production monitor.

Reuses the EXISTING owner channel: Telegram (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID),
the same transport as backend/app/services/observability.py. Delivery failures are
RETURNED, never swallowed — the monitor's self-health depends on knowing a send failed.
Secrets (bot token) are never logged or placed in any returned/printed value.
"""
from __future__ import annotations
import os, json, urllib.request, urllib.error
from dataclasses import dataclass


@dataclass
class DeliveryResult:
    ok: bool
    adapter: str
    detail: str = ""     # never contains secrets


class TestAdapter:
    """Captures messages instead of sending — for tests and dry runs."""
    name = "test"
    def __init__(self):
        self.sent = []
    def send(self, text: str) -> DeliveryResult:
        self.sent.append(text)
        return DeliveryResult(ok=True, adapter=self.name, detail=f"captured({len(self.sent)})")


class TelegramAdapter:
    """Real owner delivery via Telegram bot API (same channel as observability.notify)."""
    name = "telegram"
    API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token=None, chat_id=None, timeout=10):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> DeliveryResult:
        if not self.configured():
            # honest failure — missing channel creds, not a silent no-op
            return DeliveryResult(ok=False, adapter=self.name, detail="channel not configured (TELEGRAM_BOT_TOKEN/CHAT_ID absent)")
        url = self.API.format(token=self.token)
        data = json.dumps({"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                ok = r.status == 200
                return DeliveryResult(ok=ok, adapter=self.name, detail=f"HTTP {r.status}")
        except urllib.error.HTTPError as e:
            # do NOT echo the URL (carries the token) — only the status code
            return DeliveryResult(ok=False, adapter=self.name, detail=f"HTTP {e.code}")
        except Exception as e:
            return DeliveryResult(ok=False, adapter=self.name, detail=f"{type(e).__name__}")


def deliver(alerts, adapter) -> list:
    """Send each alert's rendered text; return (alert, DeliveryResult) pairs. Failures surfaced."""
    results = []
    for a in alerts:
        res = adapter.send(a.render_text())
        results.append((a, res))
    return results


def _demo():
    from ops.monitor.core import Alert, HIGH
    t = TestAdapter()
    a = Alert(signal="app_b_5xx", severity=HIGH, summary="App B unreachable", service="app_b")
    a.timestamp = "T"; a.alert_id = a.compute_id()
    res = deliver([a], t)
    assert res[0][1].ok and len(t.sent) == 1, "test adapter captures"
    assert "wv_session" not in t.sent[0], "no secret in rendered text"
    # unconfigured telegram fails honestly (not a silent success)
    tg = TelegramAdapter(token="", chat_id="")
    r = tg.send("x")
    assert r.ok is False and "not configured" in r.detail, "unconfigured channel returns honest failure"
    print("delivery self-check: PASS")

if __name__ == "__main__":
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    _demo()
