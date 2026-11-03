"""The morning message (core/board/day.py render_report, core/board/jobs.py) and
the board's scheduler (narai/integrations/scheduler.py start_board_scheduler):
the four numbers, the stop rule and the sources in the plan's format, every
value escaped; each channel is claimed once per day, so the message goes out
exactly once, also when a deploy lands around 07:00. No network: Stripe,
Supabase and Telegram are faked; Kit, Instantly and Meta are only configured
(their rows go in through core.board.ledger)."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from core.board import day as board_day
from core.board import jobs, ledger
from core.board.connectors import stripe_sync
from tests import board_fakes as bf

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 on Mon 2 Nov in New York
NY = board_day.NY


def ny(hour, minute=0, second=0, day=2):
    """An instant on `day` Nov 2026 at hour:minute in New York."""
    return datetime(2026, 11, day, hour, minute, second, tzinfo=NY)


@pytest.fixture(autouse=True)
def no_connector_settings(monkeypatch):
    """Kit, Instantly and Meta start unconfigured, whatever this machine has set."""
    bf.clear_connectors(monkeypatch)


@pytest.fixture
def db(monkeypatch):
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    return db


@pytest.fixture
def stripe(monkeypatch):
    return bf.install_stripe(monkeypatch)


@pytest.fixture
def synced(db, stripe):
    stripe.add(*bf.fixture_day())
    assert stripe_sync.run(now=NOW)["status"] == "ok"
    return db


class Telegram:
    """A fake channel: records each message; answers what `ok` says."""

    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, text):
        self.sent.append(text)
        if isinstance(self.ok, Exception):
            raise self.ok
        return self.ok


@pytest.fixture
def telegram(monkeypatch):
    t = Telegram()
    monkeypatch.setattr(jobs, "CHANNELS", {"telegram": (lambda: True, t)})
    return t


def _report(**kw):
    return jobs.morning_report(sync_budget=0, **kw)


# ─── the message ────────────────────────────────────────────────────────────

def test_the_message_for_the_plans_fixture_day(synced, monkeypatch):
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(synced)
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert text == ("<b>Sun 1 Nov</b> (New York; a 25-hour day: clocks went back)\n"
                    "Toodle opt-ins: 2 · target 3 · meta 1, organic 1\n"
                    "SiteBoost replies: 1 · last 7 days: 2 (target 1 a week) · 1 automatic reply or bounce "
                    "ignored\n"
                    "Revenue: $10.00 net · fees $3.17\n"
                    "  Stripe $10.00: 1 sale, 1 refund, 1 dispute, 1 dispute won\n"
                    "Meta: Toodle spend $5.02 · 9 link clicks → 2 opt-ins\n"
                    "Stop rule: CPL $6.28 over the last 5 spend days (4 Meta opt-ins) → STOP (above $5.00)\n"
                    "Sources: Stripe final · Kit final · Instantly final · Meta final")


def test_the_message_with_stripe_alone_says_what_each_other_source_needs(synced):
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert text == ("<b>Sun 1 Nov</b> (New York; a 25-hour day: clocks went back)\n"
                    "Toodle opt-ins: not connected (Kit key not set: KIT_API_KEY)\n"
                    "SiteBoost replies: not connected (no Instantly key: set INSTANTLY_API_KEY "
                    "(a key with the emails:read scope))\n"
                    "Revenue: $10.00 net · fees $3.17\n"
                    "  Stripe $10.00: 1 sale, 1 refund, 1 dispute, 1 dispute won\n"
                    "Meta: not connected (Meta token not set: META_INSIGHTS_TOKEN (or META_ACCESS_TOKEN))\n"
                    "Stop rule: not connected (needs Meta and Kit)\n"
                    "Sources: Stripe final · Kit not connected · Instantly not connected · Meta not connected")


def test_a_source_that_is_not_connected_never_reads_zero(db, monkeypatch):
    monkeypatch.delenv("STRIPE_READ_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert "Revenue: not connected (Stripe key not set" in text and "$0" not in text
    assert text.endswith("Sources: Stripe not connected · Kit not connected · Instantly not connected · "
                         "Meta not connected")
    db.down = True
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert text.split("\n")[1:] == ["Toodle opt-ins: not connected (database not connected)",
                                    "SiteBoost replies: not connected (database not connected)",
                                    "Revenue: not connected (database not connected)",
                                    "Meta: not connected (database not connected)",
                                    "Stop rule: not connected (database not connected)",
                                    "Sources: Stripe not connected · Kit not connected · Instantly not connected · "
                                    "Meta not connected"]


def test_a_real_zero_reads_zero(db, stripe):
    db.set_source(measured_from="2026-01-01", synced_through="2026-11-02T11:55:00Z")
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert "Revenue: $0.00 net · fees $0.00" in text and "Stripe $0.00: no sales" in text


def test_a_partial_day_says_so(db, stripe):
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc))
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert "Revenue: -$19.99 net so far · fees $2.00 (partial)" in text   # the dispute fee came back
    assert "synced to 17:55 on Sun 1 Nov (New York)" in text and "Sources: Stripe partial" in text


def test_every_value_in_the_message_is_escaped(synced):
    synced.set_source(last_error="<b>boom</b> & <a href=x>", last_error_at="2026-11-02T11:00:00Z")
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert "&lt;b&gt;boom&lt;/b&gt; &amp; &lt;a href=x&gt;" in text
    assert "<a href" not in text and text.count("<b>") == 1


def _lines(day="2026-11-01"):
    return board_day.render_report(board_day.day_view(date.fromisoformat(day))).split("\n")


def test_a_partial_day_says_so_on_every_line(db, stripe, monkeypatch):
    bf.configure_connectors(monkeypatch)
    stripe.add(*bf.fixture_day())
    stripe_sync.run(now=datetime(2026, 11, 1, 22, 5, tzinfo=timezone.utc))         # covered to 17:00 EST
    bf.load_fixture_leads(db, synced_through="2026-11-01T22:00:00Z")
    assert _lines()[1:] == [
        "Toodle opt-ins: 2 so far · target 3 · meta 1, organic 1",
        "  synced to 17:00 on Sun 1 Nov (New York)",
        "SiteBoost replies: 1 so far · last 7 days: 2 (target 1 a week) · 1 automatic reply or bounce ignored",
        "  synced to 17:00 on Sun 1 Nov (New York)",
        "Revenue: -$19.99 net so far · fees $2.00 (partial)",
        "  Stripe -$19.99: 1 refund, 1 dispute, 1 dispute won",
        "  synced to 17:00 on Sun 1 Nov (New York)",
        "Meta: Toodle spend $5.02 so far · 9 link clicks → 2 opt-ins",
        "  synced to 17:00 on Sun 1 Nov (New York)",
        "Stop rule: no verdict yet (waiting for Kit to finish Sun 1 Nov)",          # its evening is not read
        "Sources: Stripe partial · Kit partial · Instantly partial · Meta partial"]


def test_a_source_no_sync_has_reached_has_no_number_and_no_zero(db, monkeypatch):
    bf.configure_connectors(monkeypatch, "kit", "meta_ads")
    bf.load_fixture_leads(db)
    db.set_source("kit", synced_through="2026-10-31T12:00:00Z")                 # Kit stopped on Saturday
    ledger.mark_source_error("kit", "Kit refused the API key (HTTP 401): check KIT_API_KEY")
    lines = _lines()
    assert lines[1] == ("Toodle opt-ins: no number yet (not synced into this day yet: synced to 08:00 on "
                        "Sat 31 Oct (New York) · last sync failed: Kit refused the API key (HTTP 401): "
                        "check KIT_API_KEY)")
    assert lines[2].startswith("SiteBoost replies: not connected (no Instantly key")
    assert lines[4] == "Meta: Toodle spend $5.02 · 9 link clicks → opt-ins not counted yet"
    assert lines[5] == "Stop rule: no verdict yet (waiting for Kit to finish Sun 1 Nov)"
    assert lines[6] == "Sources: Stripe not connected · Kit partial · Instantly not connected · Meta final"


def test_the_meta_line_names_the_ad_accounts_days_and_waits_for_dollars(db, monkeypatch):
    bf.configure_connectors(monkeypatch, "meta_ads")
    for source_id in ("kit", "instantly", "meta_ads"):
        db.set_source(source_id, measured_from="2026-01-01", synced_through="2026-11-02T11:55:00Z")
    bf.record_meta_run(db)                                    # the Meta run, with the Toodle campaign listed
    ledger.update_source("meta_ads", day_tz="Europe/Berlin", currency="EUR", account_ref="act_1234567890")
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 450, currency="EUR", link_clicks=1)])
    assert _lines()[4:6] == [
        "Meta: no number yet (Meta counts days in the ad account's time zone (Europe/Berlin), not New York time "
        "· 1 spend row has no US dollar amount yet (no exchange rate), so the spend is not shown)",
        "Stop rule: not connected (needs Kit)"]
    db.add_fx_rate("EUR", "2026-10-30", "1.1")
    ledger.fill_fx()
    assert _lines()[4:6] == [
        "Meta: Toodle spend $4.95 · 1 link click → opt-ins not connected",
        "  Meta counts days in the ad account's time zone (Europe/Berlin), not New York time"]


def test_counts_of_one_read_in_the_singular(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    for source_id in ("kit", "instantly", "meta_ads"):
        db.set_source(source_id, measured_from="2026-01-01", synced_through="2026-11-02T11:55:00Z")
    bf.record_meta_run(db)                                    # the Meta run, with the Toodle campaign listed
    ledger.ingest_leads("kit", None, [bf.optin(7, "2026-11-01T16:00:00Z")])          # no channel tag yet
    ledger.ingest_leads("instantly", None, [bf.reply("e1", "2026-11-01T13:00:00Z", "p@shop.example", auto=True),
                                            bf.reply("e2", "2026-11-01T14:00:00Z", "q@shop.example", auto=True)])
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-11-01", 100, link_clicks=1)])
    assert _lines()[1:3] == ["Toodle opt-ins: 1 · target 3 · unknown 1",
                             "SiteBoost replies: 0 · last 7 days: 0 (target 1 a week) · 2 automatic replies or "
                             "bounces ignored"]
    assert _lines()[4:6] == ["Meta: Toodle spend $1.00 · 1 link click → 1 opt-in",
                             "Stop rule: collecting, 1 of 5 spend days so far"]


def test_without_toodle_campaigns_the_message_shows_no_toodle_spend_and_no_verdict(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    bf.load_fixture_leads(db)
    _, _, spend_rows = bf.fixture_leads()           # as the Meta sync writes them with no Toodle campaign listed
    ledger.upsert_ad_spend("meta_ads", None, [r for r in spend_rows if r.funnel is None] +
                           [bf.spend(r.day.isoformat(), r.spend_minor, funnel=None) for r in spend_rows if r.funnel])
    ledger.mark_source_ok("meta_ads", datetime(2026, 11, 2, 11, 55, tzinfo=timezone.utc),
                          warning="BOARD_TOODLE_META_CAMPAIGN_IDS is not set, so no Meta spend counts as Toodle spend")
    lines = _lines()
    assert lines[4:7] == [
        "Meta: not connected (Toodle campaigns not set: BOARD_TOODLE_META_CAMPAIGN_IDS names no campaign · "
        "last sync: BOARD_TOODLE_META_CAMPAIGN_IDS is not set, so no Meta spend counts as Toodle spend)",
        "Stop rule: not connected (Toodle campaigns not set: BOARD_TOODLE_META_CAMPAIGN_IDS names no campaign)",
        "Sources: Stripe not connected · Kit final · Instantly final · Meta final"]
    assert "$0.00" not in "\n".join(lines) and "no Toodle ad spend" not in "\n".join(lines)


def test_a_7_day_reply_count_with_unmeasured_days_is_left_out_and_says_why(db, monkeypatch):
    bf.configure_connectors(monkeypatch)
    bf.load_fixture_leads(db)
    db.set_source("instantly", measured_from="2026-10-28")
    assert _lines()[2:4] == ["SiteBoost replies: 1 · 1 automatic reply or bounce ignored",
                             "  no 7-day count: replies are counted only from 2026-10-28"]
    db.set_source("instantly", synced_through="2026-11-04T11:55:00Z")
    assert _lines("2026-11-03")[2] == "SiteBoost replies: 0 · last 7 days: 2 (target 1 a week)"   # 28 Oct to 3 Nov


def test_hostile_names_and_errors_are_escaped_in_the_message(synced, monkeypatch):
    bf.configure_connectors(monkeypatch)
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:,<b>vip</b>:meta")
    bf.load_fixture_leads(synced)
    synced.leads[("kit", "toodle:sub:2")]["channel"] = "<i>meta</i>&co"   # a channel the SQL would never store
    ledger.mark_source_ok("kit", datetime(2026, 11, 2, 11, 55, tzinfo=timezone.utc),
                          warning='tag "<b>vip</b>" is not in Kit')
    ledger.mark_source_error("meta_ads", "Meta refused the read <script>alert(1)</script>")
    text = board_day.render_report(board_day.day_view(date(2026, 11, 1)))
    assert "Toodle opt-ins: 2 · target 3 · &lt;i&gt;meta&lt;/i&gt;&amp;co 1, organic 1" in text
    assert '  last sync: tag "&lt;b&gt;vip&lt;/b&gt;" is not in Kit' in text
    assert "last sync failed: Meta refused the read &lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<i>" not in text and "<script" not in text and text.count("<b>") == 1 and text.count("</b>") == 1


# ─── sent once per day and channel ──────────────────────────────────────────

def test_the_report_is_sent_once_for_yesterday(synced, telegram):
    first = _report()
    assert first == {"status": "done", "day": "2026-11-01", "channels": {"telegram": "sent"}}
    assert len(telegram.sent) == 1 and "Revenue: $10.00 net" in telegram.sent[0]
    second = _report(trigger="startup")
    assert second["channels"] == {"telegram": "sent already or sending"} and len(telegram.sent) == 1
    (run,) = synced.runs("morning_report")
    assert (run["run_key"], run["status"], run["attempts"]) == ("2026-11-01:telegram", "ok", 1)
    assert run["detail"]["channel"] == "telegram" and run["finished_at"] is not None
    # yesterday, decided in SQL; the stop rule's settings go with every call
    assert synced.rpc_calls("board_day")[-1] == {"p_day": None, "p_cpl_days": 5, "p_cpl_stop_cents": 500}


def test_a_failed_send_is_marked_failed_then_claimed_again_and_never_sent_twice(synced, telegram):
    telegram.ok = False
    assert _report()["channels"] == {"telegram": "failed"}
    (run,) = synced.runs("morning_report")
    assert run["status"] == "failed" and "did not accept" in run["error"]
    telegram.ok = True
    assert _report()["channels"] == {"telegram": "sent"}
    assert synced.runs("morning_report")[0]["attempts"] == 2
    assert _report()["channels"] == {"telegram": "sent already or sending"}
    assert len(telegram.sent) == 2                                  # the failed try and the one that went out
    telegram.ok = RuntimeError("network down")
    synced.job_runs.clear()
    assert _report()["channels"] == {"telegram": "failed"}
    assert "RuntimeError" in synced.runs("morning_report")[0]["error"]


def test_no_configured_channel_sends_and_claims_nothing(synced, monkeypatch):
    monkeypatch.setattr(jobs, "CHANNELS", {"telegram": (lambda: False, Telegram())})
    assert jobs.morning_report()["status"] == "skipped"
    assert synced.runs("morning_report") == [] and synced.rpc_calls("board_day") == []


def test_without_a_claim_nothing_is_sent(synced, telegram):
    synced.fail["rpc/board_claim_run"] = 503
    assert _report()["channels"] == {"telegram": "not claimed"}
    assert telegram.sent == []


def test_the_report_runs_the_hourly_syncs_first_within_one_budget(synced, telegram, monkeypatch):
    order = []
    for name in ("sync_stripe", "sync_kit", "sync_instantly", "sync_meta"):
        monkeypatch.setattr(jobs, name, lambda trigger, n=name: order.append((n, trigger)))
    real_claim = jobs.ledger.claim_run
    monkeypatch.setattr(jobs.ledger, "claim_run",
                        lambda *a, **k: order.append(("claim", a[1])) or real_claim(*a, **k))
    jobs.morning_report(sync_budget=5)
    assert sorted(order[:3]) == [("sync_instantly", "schedule"), ("sync_kit", "schedule"),
                                 ("sync_stripe", "schedule")]
    assert order[3:] == [("claim", "2026-11-01:telegram")]          # Meta is not configured: not synced
    order.clear()
    for name in ("sync_stripe", "sync_kit", "sync_instantly"):
        monkeypatch.setattr(jobs, name, lambda trigger: __import__("time").sleep(2))
    started = datetime.now()
    jobs.morning_report(sync_budget=0.6, trigger="startup")          # slow syncs do not hold the report:
    assert (datetime.now() - started).total_seconds() < 1.5        # one budget for all, not 1.8 s for 3


# ─── the first message after the first deploy ───────────────────────────────

@pytest.fixture
def slow_first_backfill(monkeypatch):
    """Stripe's first sync takes longer than the report's sync budget."""
    real_run = stripe_sync.run

    def run(trigger="schedule", days=None, now=None):
        __import__("time").sleep(0.3)
        return real_run(trigger=trigger, days=days, now=NOW)

    monkeypatch.setattr(stripe_sync, "run", run)
    monkeypatch.setattr(jobs, "_POLL", 0.02)


def test_the_first_message_waits_for_the_first_backfill(db, stripe, telegram, slow_first_backfill):
    stripe.add(*bf.fixture_day())
    out = jobs.morning_report(trigger="startup", sync_budget=0.05)     # the budget runs out first
    assert out["channels"] == {"telegram": "sent"}
    (text,) = telegram.sent
    assert "Revenue: $10.00 net" in text and "Revenue: not connected" not in text and "Stripe final" in text
    assert db.sources["stripe"]["measured_from"] == date(2026, 1, 1)


def test_the_first_message_waits_for_a_first_sync_started_elsewhere(db, stripe, telegram, monkeypatch):
    stripe.add(*bf.fixture_day())
    monkeypatch.setattr(jobs, "sync_stripe", lambda trigger: {"status": "busy"})    # the owner's Sync button
    waits = []

    def the_other_run_finishes(seconds):
        waits.append(seconds)
        if len(waits) == 1:
            assert stripe_sync.run(now=NOW)["status"] == "ok"

    monkeypatch.setattr(jobs, "_sleep", the_other_run_finishes)
    assert jobs.morning_report(sync_budget=5)["channels"] == {"telegram": "sent"}
    assert len(waits) == 1 and "Revenue: $10.00 net" in telegram.sent[0]


def test_a_failing_first_sync_does_not_hold_the_message(db, stripe, telegram, monkeypatch):
    stripe.add(*bf.fixture_day())
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_live_FAKEotherKey1")           # Stripe refuses it
    monkeypatch.setattr(jobs, "_sleep", lambda seconds: pytest.fail("waited after the sync failed"))
    assert jobs.morning_report(sync_budget=5)["channels"] == {"telegram": "sent"}
    assert "Revenue: not connected" in telegram.sent[0] and "last sync failed: Stripe HTTP 401" in telegram.sent[0]


def test_no_wait_once_stripe_has_synced_or_without_a_live_key(synced, monkeypatch):
    monkeypatch.setattr(jobs, "_sleep", lambda seconds: pytest.fail("waited"))
    assert jobs._first_sync_pending() is False                          # measured since 1 Jan
    synced.set_source(measured_from=None)
    assert jobs._first_sync_pending() is True
    monkeypatch.setenv("STRIPE_READ_KEY", "rk_test_FAKEboardTest2")
    assert jobs._first_sync_pending() is False                          # the sync refuses a test key
    monkeypatch.delenv("STRIPE_READ_KEY")
    assert jobs._first_sync_pending() is False


# ─── catch-up at startup, and a deploy around 07:00 ─────────────────────────

@pytest.fixture
def seven_am():
    triggers = pytest.importorskip("apscheduler.triggers.cron")
    return triggers.CronTrigger.from_crontab("0 7 * * *", timezone="America/New_York")


def test_catch_up_only_after_the_report_time_and_before_noon(synced, telegram, seven_am):
    assert jobs.catch_up(seven_am, now=ny(6, 59))["reason"] == "before today's report time"
    assert jobs.catch_up(seven_am, now=ny(12, 0))["reason"] == "after noon in New York"
    assert telegram.sent == []
    assert jobs.catch_up(seven_am, now=ny(9, 30))["channels"] == {"telegram": "sent"}
    assert jobs.catch_up(seven_am, now=ny(9, 31))["channels"] == {"telegram": "sent already or sending"}
    assert len(telegram.sent) == 1
    assert synced.runs("morning_report")[0]["trigger_kind"] == "startup"


def test_a_deploy_at_0659_still_yields_exactly_one_message(synced, telegram, seven_am):
    # the new container starts at 06:59: too early to catch up
    assert jobs.catch_up(seven_am, now=ny(6, 59))["status"] == "skipped"
    # 07:00: the old container, still up, and the new one both fire the cron
    old, new = _report(), _report()
    assert old["channels"] == {"telegram": "sent"}
    assert new["channels"] == {"telegram": "sent already or sending"}
    # a third container that came up at 07:00:30 catches up and finds it sent
    assert jobs.catch_up(seven_am, now=ny(7, 0, 30))["channels"] == {"telegram": "sent already or sending"}
    assert len(telegram.sent) == 1


def test_a_deploy_that_misses_0700_catches_up_once(synced, telegram, seven_am):
    # the old container stopped at 06:59:50; the new one is up at 07:00:20
    assert jobs.catch_up(seven_am, now=ny(7, 0, 20))["channels"] == {"telegram": "sent"}
    assert _report()["channels"] == {"telegram": "sent already or sending"}      # a late cron firing
    assert len(telegram.sent) == 1


def test_a_report_left_running_by_a_dead_container_is_sent_after_30_minutes(synced, telegram):
    synced._rpc_board_claim_run("morning_report", "2026-11-01:telegram", "schedule")   # died mid-send
    assert _report()["channels"] == {"telegram": "sent already or sending"}
    synced.clock = lambda: NOW + timedelta(minutes=31)
    assert _report()["channels"] == {"telegram": "sent"}
    assert synced.runs("morning_report")[0]["attempts"] == 2 and len(telegram.sent) == 1


# ─── the scheduler ──────────────────────────────────────────────────────────

@pytest.fixture
def scheduler(monkeypatch):
    pytest.importorskip("apscheduler")
    from narai.integrations import scheduler as sched
    monkeypatch.setattr(sched, "_board_scheduler", None)
    monkeypatch.setattr(sched, "_scheduler", None)
    return sched


def test_the_board_scheduler_runs_on_new_york_time_without_telegram(scheduler, monkeypatch):
    caught = []
    monkeypatch.setattr(jobs, "catch_up", lambda trigger, now=None: caught.append(trigger))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BOARD_REPORT_CRON", raising=False)
    monkeypatch.setenv("NARAI_BRIEFING_TZ", "Europe/Paris")          # the board ignores it

    async def main():
        scheduler.start_board_scheduler()
        first = scheduler._board_scheduler
        scheduler.start_board_scheduler()                              # idempotent
        assert scheduler._board_scheduler is first
        found = {j.id: j for j in first.get_jobs()}
        await asyncio.sleep(0.3)                                       # the one-off catch-up runs now
        scheduler.stop_board_scheduler()
        await asyncio.sleep(0)
        return found

    found = asyncio.run(main())
    assert set(found) == {"board_sync_hourly", "board_meta", "board_morning_report", "board_report_catch_up"}
    hourly, meta, report = found["board_sync_hourly"], found["board_meta"], found["board_morning_report"]
    assert hourly.func is jobs.sync_hourly and meta.func is jobs.sync_meta and report.func is jobs.morning_report
    for job in (hourly, meta, report):
        assert str(job.trigger.timezone) == "America/New_York"
        assert (job.coalesce, job.max_instances, job.misfire_grace_time) == (True, 1, 900)
        assert job.args == () and job.kwargs == {}                   # each body's own defaults: trigger "schedule"
    fields = {f.name: str(f) for f in hourly.trigger.fields}
    assert (fields["minute"], fields["hour"], fields["day_of_week"]) == ("7", "*", "*")
    fields = {f.name: str(f) for f in meta.trigger.fields}
    assert (fields["minute"], fields["hour"], fields["day_of_week"]) == ("30", "6,12", "*")
    fields = {f.name: str(f) for f in report.trigger.fields}
    assert (fields["minute"], fields["hour"], fields["day_of_week"]) == ("0", "7", "*")
    assert caught == [found["board_report_catch_up"].args[0]] and caught[0] is report.trigger
    assert scheduler._board_scheduler is None


def test_the_app_starts_and_stops_the_board_scheduler(scheduler):
    import core.api as api
    assert scheduler.start_board_scheduler in api._DEFERRED_STARTUP_HANDLERS
    assert scheduler.stop_board_scheduler in api._DEFERRED_SHUTDOWN_HANDLERS


def test_a_bad_report_cron_falls_back_to_0700(scheduler, monkeypatch):
    monkeypatch.setattr(jobs, "catch_up", lambda trigger, now=None: None)
    monkeypatch.setenv("BOARD_REPORT_CRON", "every morning")

    async def main():
        scheduler.start_board_scheduler()
        job = scheduler._board_scheduler.get_job("board_morning_report")
        scheduler.stop_board_scheduler()
        await asyncio.sleep(0)
        return job

    fields = {f.name: str(f) for f in asyncio.run(main()).trigger.fields}
    assert (fields["minute"], fields["hour"]) == ("0", "7")


def test_the_briefing_scheduler_still_uses_the_lifted_cron_helper(scheduler, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake-token-for-tests")
    monkeypatch.setenv("NARAI_BRIEFING_CRON", "not a cron")
    monkeypatch.setenv("NARAI_RECAP_CRON", "off")

    async def main():
        scheduler.start_briefing_scheduler()
        found = {j.id: j for j in scheduler._scheduler.get_jobs()}
        scheduler.stop_briefing_scheduler()
        await asyncio.sleep(0)
        return found

    found = asyncio.run(main())
    assert set(found) == {"daily_briefing_morning"}
    fields = {f.name: str(f) for f in found["daily_briefing_morning"].trigger.fields}
    assert (fields["hour"], fields["day_of_week"]) == ("7", "1-5")          # the fallback, 0 7 * * 1-5
    trigger = scheduler._safe_trigger("61 * * * *", "7 * * * *", "America/New_York")
    assert {f.name: str(f) for f in trigger.fields}["minute"] == "7"
