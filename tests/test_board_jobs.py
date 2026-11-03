"""The board's sync jobs (core/board/jobs.py) and POST /api/board/sync/<source>
for Kit, Instantly and Meta: the hourly job runs the Stripe, Kit and Instantly
syncs each isolated, so one that fails, raises or hangs never stops the others
or the scheduler; the morning report syncs Meta first only when Meta has no ok
run since 06:00 New York time; and the sync route is the owner's only, from
the board's own origin, once a minute per source. No network: the connectors'
run() is replaced, or runs unconfigured (it then calls nothing), and Supabase
is faked in tests/board_fakes.py. The scheduler's ids and triggers are checked
in tests/test_board_report.py."""
import threading
import time
from datetime import datetime, timezone

import pytest

from core.board import jobs, routes
from core.board.connectors import instantly_sync, kit_sync, meta_sync, stripe_sync
from tests import board_fakes as bf

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 on Mon 2 Nov in New York (EST)
SAME_ORIGIN = {"Origin": "http://testserver"}
CONNECTORS = {"stripe": stripe_sync, "kit": kit_sync, "instantly": instantly_sync, "meta_ads": meta_sync}
NEW_SOURCES = ("kit", "instantly", "meta_ads")


@pytest.fixture(autouse=True)
def no_connector_settings(monkeypatch):
    """Every connector starts unconfigured, whatever this machine has set."""
    bf.clear_connectors(monkeypatch)


@pytest.fixture
def db(monkeypatch):
    db = bf.install_board(monkeypatch)
    db.clock = lambda: NOW
    return db


class Runs:
    """Stands in for each connector's run(trigger, days): records every call
    (from any thread) and answers with `answers[source]`, a status ('ok' by
    default) or an exception to raise. A source in `hold` waits for
    `release` first, as a sync that hangs."""

    def __init__(self, monkeypatch):
        self.calls: list[tuple] = []
        self.answers: dict = {}
        self.hold: set = set()
        self.release = threading.Event()
        self._lock = threading.Lock()
        for source, module in CONNECTORS.items():
            monkeypatch.setattr(module, "run", self._runner(source))

    def _runner(self, source):
        def run(trigger="schedule", days=None, now=None):
            with self._lock:
                self.calls.append((source, trigger, days))
            if source in self.hold:
                self.release.wait(5)
            answer = self.answers.get(source, "ok")
            if isinstance(answer, BaseException):
                raise answer
            return {"id": f"run-{source}", "source_id": source, "trigger_kind": trigger, "status": answer,
                    "error": None if answer == "ok" else f"{source} {answer}"}
        return run

    def sources(self) -> list[str]:
        return sorted(source for source, _, _ in self.calls)


@pytest.fixture
def runs(monkeypatch):
    fake = Runs(monkeypatch)
    yield fake
    fake.release.set()                 # never leave a held thread behind


class FrozenDatetime(datetime):
    """jobs.datetime at NOW, so "since 06:00 today" is 06:00 on 2 Nov."""

    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


@pytest.fixture
def telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(jobs, "CHANNELS", {"telegram": (lambda: True, lambda text: sent.append(text) or True)})
    return sent


# ─── the hourly job: Stripe, Kit and Instantly, each isolated ───────────────

def test_the_hourly_job_runs_stripe_kit_and_instantly_once_each(runs):
    assert jobs.sync_hourly() == {"stripe": "ok", "kit": "ok", "instantly": "ok"}
    assert sorted(runs.calls) == [("instantly", "schedule", None), ("kit", "schedule", None),
                                  ("stripe", "schedule", None)]


def test_a_kit_failure_never_stops_instantly_or_stripe(runs, caplog):
    runs.answers["kit"] = RuntimeError("Kit went away")
    assert jobs.sync_hourly() == {"stripe": "ok", "kit": "failed", "instantly": "ok"}
    assert "kit sync job failed" in caplog.text
    runs.answers["kit"] = "failed"                                    # a run that recorded its own failure
    assert jobs.sync_hourly() == {"stripe": "ok", "kit": "failed", "instantly": "ok"}
    assert runs.sources() == ["instantly", "instantly", "kit", "kit", "stripe", "stripe"]


def test_a_job_body_that_raises_is_isolated_too(runs, monkeypatch):
    monkeypatch.setattr(jobs, "sync_stripe", lambda trigger: 1 / 0)
    assert jobs.sync_hourly() == {"stripe": "failed", "kit": "ok", "instantly": "ok"}
    assert runs.sources() == ["instantly", "kit"]


def test_a_hanging_sync_holds_neither_the_others_nor_the_job_past_its_budget(runs, monkeypatch):
    monkeypatch.setattr(jobs, "HOURLY_BUDGET", 0.3)
    runs.hold.add("stripe")
    started = time.monotonic()
    assert jobs.sync_hourly() == {"stripe": "running", "kit": "ok", "instantly": "ok"}
    assert time.monotonic() - started < 2
    runs.release.set()


def test_syncs_that_all_hang_share_one_budget_rather_than_one_each(runs, monkeypatch):
    monkeypatch.setattr(jobs, "HOURLY_BUDGET", 0.5)
    runs.hold.update(jobs.HOURLY)
    started = time.monotonic()
    assert jobs.sync_hourly() == {"stripe": "running", "kit": "running", "instantly": "running"}
    assert time.monotonic() - started < 1.25              # 0.5 s in all; a budget each would be 1.5 s


def test_every_sync_job_passes_its_trigger_and_never_raises(runs):
    for source, job in (("stripe", jobs.sync_stripe), ("kit", jobs.sync_kit),
                        ("instantly", jobs.sync_instantly), ("meta_ads", jobs.sync_meta)):
        runs.answers[source] = ValueError("boom")
        assert job(trigger="owner") == {"status": "failed"}
        runs.answers[source] = "ok"
        assert job()["status"] == "ok"
    assert [c for c in runs.calls if c[0] == "meta_ads"] == [("meta_ads", "owner", None),
                                                             ("meta_ads", "schedule", None)]


def test_unconfigured_syncs_are_skipped_and_call_nothing(db, monkeypatch):
    monkeypatch.delenv("STRIPE_READ_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert jobs.sync_hourly() == {"stripe": "skipped", "kit": "skipped", "instantly": "skipped"}
    assert jobs.sync_meta()["status"] == "skipped"
    assert db.calls == []                                             # no claim, no read


# ─── the morning report: Meta first when it has no ok run since 06:00 ───────

@pytest.mark.parametrize("last_ok, due", [
    (None, True),                              # never synced
    ("2026-11-01T17:30:00Z", True),            # 12:30 yesterday
    ("2026-11-02T10:59:00Z", True),            # 05:59 today
    ("2026-11-02T11:00:00Z", False),           # 06:00 today
    ("2026-11-02T11:30:00Z", False),           # 06:30 today, the board_meta job
])
def test_the_report_syncs_meta_only_without_an_ok_run_since_six(db, runs, telegram, monkeypatch, last_ok, due):
    bf.configure_connectors(monkeypatch, "meta_ads")
    db.set_source("meta_ads", last_ok_at=last_ok)
    monkeypatch.setattr(jobs, "datetime", FrozenDatetime)
    assert jobs._meta_due(NOW) is due
    assert jobs.morning_report(sync_budget=5)["channels"] == {"telegram": "sent"}
    assert runs.sources() == (["instantly", "kit", "meta_ads", "stripe"] if due else ["instantly", "kit", "stripe"])


def test_the_report_leaves_meta_alone_when_meta_is_not_configured(db, runs, telegram):
    assert jobs._meta_due(NOW) is False
    jobs.morning_report(sync_budget=5)
    assert runs.sources() == ["instantly", "kit", "stripe"]
    assert not [c for c in db.calls if "meta_ads" in str(c.url)]     # not even its source row is read


def test_the_report_syncs_meta_when_the_database_cannot_say(db, runs, telegram, monkeypatch):
    bf.configure_connectors(monkeypatch, "meta_ads")
    db.fail["sources"] = 503
    assert jobs._meta_due(NOW) is True                               # the run itself then fails before Meta


def test_the_catch_up_report_passes_its_trigger_to_every_sync(db, runs, telegram, monkeypatch):
    cron = pytest.importorskip("apscheduler.triggers.cron")
    seven = cron.CronTrigger.from_crontab("0 7 * * *", timezone="America/New_York")
    bf.configure_connectors(monkeypatch, "meta_ads")
    monkeypatch.setattr(jobs, "datetime", FrozenDatetime)
    out = jobs.catch_up(seven, now=datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc))     # 09:30 in New York
    assert out["channels"] == {"telegram": "sent"}
    assert sorted(runs.calls) == [(s, "startup", None) for s in ("instantly", "kit", "meta_ads", "stripe")]


# ─── the route: POST /api/board/sync/{kit,instantly,meta_ads} ───────────────

@pytest.fixture
def owner(monkeypatch):
    fake = bf.install(monkeypatch)
    monkeypatch.setattr(routes, "_last_sync", {})
    return bf.client(monkeypatch), bf.cookie(fake.add_session())


def test_the_route_knows_every_source():
    assert routes.SYNCS == {"stripe": stripe_sync, "kit": kit_sync, "instantly": instantly_sync,
                            "meta_ads": meta_sync}


@pytest.mark.parametrize("source", NEW_SOURCES)
def test_the_sync_route_needs_the_owner_and_the_boards_own_origin(owner, runs, source):
    client, cookie = owner
    url = f"/api/board/sync/{source}"
    assert client.post(url, headers=SAME_ORIGIN).status_code == 401
    assert client.post(url, headers={"X-API-Key": bf.API_KEY, **SAME_ORIGIN}).status_code == 401
    assert client.post(url, headers={**cookie, "Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, headers=cookie).status_code == 403                     # no Origin at all
    assert client.get(url, headers={**cookie, **SAME_ORIGIN}).status_code == 405
    assert runs.calls == []


@pytest.mark.parametrize("source", NEW_SOURCES)
def test_the_sync_route_runs_one_sync_a_minute_per_source(owner, runs, source):
    client, cookie = owner
    headers = {**cookie, **SAME_ORIGIN}
    r = client.post(f"/api/board/sync/{source}?days=10", headers=headers)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["trigger_kind"]) == ("ok", "owner")
    assert "no-store" in r.headers["cache-control"]
    assert runs.calls == [(source, "owner", 10)]
    again = client.post(f"/api/board/sync/{source}", headers=headers)
    assert again.status_code == 429 and int(again.headers["retry-after"]) >= 1
    other = next(s for s in CONNECTORS if s != source)
    assert client.post(f"/api/board/sync/{other}", headers=headers).status_code == 200   # its own minute
    assert runs.calls == [(source, "owner", 10), (other, "owner", None)]


@pytest.mark.parametrize("source", NEW_SOURCES)
def test_the_sync_route_answers_each_outcome(owner, runs, monkeypatch, source):
    client, cookie = owner
    headers = {**cookie, **SAME_ORIGIN}
    for days in (0, 32):
        assert client.post(f"/api/board/sync/{source}?days={days}", headers=headers).status_code == 422
    for status, code in (("busy", 409), ("skipped", 503), ("failed", 502)):
        monkeypatch.setattr(routes, "_last_sync", {})
        runs.answers[source] = status
        r = client.post(f"/api/board/sync/{source}", headers=headers)
        assert (r.status_code, r.json()["error"]) == (code, f"{source} {status}")


@pytest.mark.parametrize("source, reason", [
    ("kit", "Kit key not set: KIT_API_KEY"),
    ("instantly", "no Instantly key: set INSTANTLY_API_KEY (a key with the emails:read scope)"),
    ("meta_ads", "Meta token not set: META_INSIGHTS_TOKEN (or META_ACCESS_TOKEN)"),
])
def test_an_unconfigured_source_answers_503_with_its_reason_and_claims_nothing(owner, db, source, reason):
    client, cookie = owner
    r = client.post(f"/api/board/sync/{source}", headers={**cookie, **SAME_ORIGIN})
    assert r.status_code == 503
    assert (r.json()["status"], r.json()["error"], r.json()["id"]) == ("skipped", reason, None)
    assert db.calls == [] and db.runs(f"{source.removesuffix('_ads')}_sync") == []
