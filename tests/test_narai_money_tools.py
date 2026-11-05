"""NarAI's money tools (bots/narai/narai/bot.py) read /api/money/*, whose
numbers are null when they are not measured. Each tool says "not measured"
for a null, never $0.00 and never a crash, and a refused entry says why in
the server's words. The invented KDP estimate is gone from what NarAI says.
No network: requests is stubbed."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _bot():
    spec = importlib.util.spec_from_file_location("narai_bot_money_tools", ROOT / "bots" / "narai" / "narai" / "bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


narai = _bot()


class Answer:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


@pytest.fixture
def bot(monkeypatch):
    import requests
    sent = []

    def get(url, timeout=10, **kwargs):
        sent.append(url)
        return Answer(bot.answers[url.split("?")[0].rsplit("/", 1)[-1]])

    def post(url, params=None, timeout=10, **kwargs):
        sent.append((url, params))
        return Answer(bot.answers["record"])

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    bot = narai.NarAIBot.__new__(narai.NarAIBot)       # no config read, no client built
    bot.answers, bot.sent = {}, sent
    return bot


NOT_MEASURED = {
    "stripe": {"today": None, "week": None, "total": None, "recent": []},
    "manual": {"today": 25.0, "week": None, "total": None},
    "ledger": {"connected": True, "note": "Stripe is not measured here (Stripe key not set)."},
    "kdp": {"published": 1, "errors": 0, "est_daily": None, "genres": {}},
    "leads": {"total": 3, "today": 1, "list_size": 7},
    "monetization": {"total_injections": 0, "total_links": 0},
    "affiliate_clicks_7d": None, "total_revenue_today": None}


def test_revenue_today_says_not_measured_for_every_null(bot):
    bot.answers["summary"] = NOT_MEASURED
    text = bot._narai_revenue_today()
    assert "**Today's total:** not measured" in text
    assert "**Stripe today:** not measured  |  Last 7 days: not measured  |  All-time: not measured" in text
    assert "**Manual entries today:** $25.00" in text
    assert "**Product clicks (7d):** not measured" in text
    assert "Stripe key not set" in text
    assert "$0.00" not in text and "Est." not in text and "royalty" not in text.lower()


def test_revenue_today_shows_measured_numbers_and_the_latest_payment_masked(bot):
    bot.answers["summary"] = {**NOT_MEASURED, "total_revenue_today": 74.0, "affiliate_clicks_7d": 3,
                              "stripe": {"today": 49.0, "week": 95.99, "total": -12.5, "recent": [
                                  {"ts": "2026-11-03T09:00:00-05:00", "type": "sale", "amount": 49.0,
                                   "currency": "usd", "email": "c***@example.com", "product": "Prompt Bible",
                                   "event_id": "txn_nov3"}]}}
    text = bot._narai_revenue_today()
    assert "**Today's total:** $74.00" in text
    assert "**Stripe today:** $49.00  |  Last 7 days: $95.99  |  All-time: -$12.50" in text
    assert "**Latest payment:** $49.00 from c***@example.com (sale)" in text
    assert "**Product clicks (7d):** 3" in text and "ℹ️" not in text


def test_stripe_payments_says_not_measured_rather_than_no_payments(bot):
    bot.answers["stripe"] = {"total": None, "count": None, "by_type": {}, "payments": [],
                             "ledger": {"note": "database not connected"}}
    assert bot._narai_stripe_payments(7) == "Stripe payments for the last 7 days are not measured: database not connected"
    bot.answers["stripe"] = {"total": 95.99, "count": 2, "by_type": {"sale": 115.98, "refund": -19.99},
                             "payments": [{"amount": None, "email": "", "type": "sale", "ts": None}]}
    text = bot._narai_stripe_payments(7)
    assert "**Net total: $95.99** across 2 transactions" in text
    assert "By type: sale: $115.98, refund: -$19.99" in text
    assert "  • not measured — anon (sale) " in text


def test_record_revenue_reports_the_servers_reason(bot):
    bot.answers["record"] = {"status": "not recorded", "error": "The amount cannot be 0."}
    assert bot._narai_record_revenue("kdp_royalty", 0) == "Not recorded: The amount cannot be 0."
    bot.answers["record"] = {"status": "recorded", "amount": 25.0, "id": "manual:x"}
    assert bot._narai_record_revenue("kdp_royalty", 25).startswith("✅ Recorded $25.00 from **kdp_royalty**.")
    assert bot.sent[-1] == ("http://localhost:5050/api/money/record",
                            {"source": "kdp_royalty", "amount": 25, "note": ""})


class Status(Answer):
    def __init__(self, status_code, body):
        super().__init__(body)
        self.status_code = status_code


def _record_with(monkeypatch, *answers):
    """NarAI's record_revenue against these answers, one per call: an
    exception to raise (no answer) or a (status, body) pair."""
    import requests
    calls = []

    def post(url, params=None, headers=None, timeout=10, **kwargs):
        calls.append(dict(headers or {}))
        answer = answers[len(calls) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return Status(*answer)

    monkeypatch.setattr(requests, "post", post)
    bot = narai.NarAIBot.__new__(narai.NarAIBot)
    return bot._narai_record_revenue("kdp_royalty", 250.0, "March"), calls


REPLAYED = (200, {"status": "recorded", "amount": 250.0, "id": "manual:idem:x", "replayed": True})


@pytest.mark.parametrize("first", ["timeout", "503"])
def test_record_revenue_sends_one_idempotency_key_and_asks_again_with_it(monkeypatch, first):
    """The server may have written the entry when its answer was lost (or
    came back as a 503): NarAI asks once more with the same key, and the
    server answers from the stored entry."""
    import requests
    lost = (requests.exceptions.ReadTimeout("the server took too long") if first == "timeout"
            else (503, {"status": "not recorded", "error": "Not recorded: the database is not connected."}))
    reply, calls = _record_with(monkeypatch, lost, REPLAYED)
    keys = [c.get("Idempotency-Key") for c in calls]
    assert len(keys) == 2 and keys[0] and keys[0] == keys[1]
    assert reply.startswith("✅ Recorded $250.00 from **kdp_royalty**.")


def test_record_revenue_says_it_could_not_confirm_when_the_server_never_finishes(monkeypatch):
    import requests
    reply, calls = _record_with(monkeypatch, requests.exceptions.ConnectionError("refused"),
                                requests.exceptions.ReadTimeout("the server took too long"))
    assert len(calls) == 2
    assert reply == ("I could not confirm it was recorded: the server did not finish. "
                     "Check the Money Command Center before recording it again.")


def test_record_revenue_asks_once_for_a_refusal(monkeypatch):
    reply, calls = _record_with(monkeypatch, (422, {"status": "not recorded", "error": "The amount cannot be 0."}))
    assert len(calls) == 1 and reply == "Not recorded: The amount cannot be 0."


def test_no_tool_describes_a_kdp_estimate():
    tools = {t["name"]: t["description"] for t in narai.NarAIBot._VOICE_TOOLS}
    assert "estimate" not in tools["revenue_today"].lower()
    assert "manual entries" in tools["revenue_today"]
    text = (ROOT / "bots" / "narai" / "narai" / "bot.py").read_text(encoding="utf-8")
    assert "KDP royalty estimates" not in text and "est_daily" not in text and "Est. monthly" not in text
