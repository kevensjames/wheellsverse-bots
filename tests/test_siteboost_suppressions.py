"""Tests for the SiteBoost CAN-SPAM opt-out list (file + Supabase).

Supabase is replaced by an in-memory fake of the supabase-py query builder, and
Instantly by a recorder — no network calls, no API keys. The background retry
never starts a thread here: its timer is recorded, and fired by hand.

Run with: pytest tests/test_siteboost_suppressions.py -v
"""
from __future__ import annotations

import copy
import inspect
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make the project root importable when pytest runs from any dir
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import cold_outreach
from core.cold_outreach import (
    SuppressionStoreError, add_suppression, backfill_suppressions, is_suppressed,
    list_suppressions, remove_suppression, suppression_store_status,
)

PROBE = cold_outreach._PROBE_EMAIL


# ── Fake Supabase table (supabase-py query-builder API, in memory) ──────────

class FakeTable:
    """Stands in for cold_outreach._table(): each call starts a new query."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.fail_reads = False
        self.fail_writes = False
        self.fail_next_writes = 0         # the next N writes raise, later ones succeed
        self.reject: set[str] = set()     # rows Postgres refuses (fails the whole statement)
        self.rls_hidden = False           # non-service key: RLS answers [] / refuses writes
        self.reads_before_failure = None  # every read after this many raises
        self.max_rows = 1000              # PostgREST caps rows per request
        self.on_write = None              # called once, at the next write
        self.n_reads = 0
        self.n_writes = 0

    def __call__(self):
        return _Query(self)

    def emails(self) -> list[str]:
        """Real opt-outs: every row but the migration's probe row."""
        return sorted(e for e in self.rows if e != PROBE)


class _Query:
    def __init__(self, table: FakeTable):
        self.t, self.op, self.filters = table, None, []
        self.lim = self.rng = self.payload = None
        self.ignore_duplicates = False

    def select(self, cols):
        self.op = "select"
        return self

    def upsert(self, rows, on_conflict="", ignore_duplicates=False):
        self.op = "upsert"
        self.payload = rows if isinstance(rows, list) else [rows]
        self.ignore_duplicates = ignore_duplicates
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, col):
        return self

    def limit(self, n):
        self.lim = n
        return self

    def range(self, start, end):
        self.rng = (start, end)
        return self

    def _matching(self) -> list[str]:
        return [e for e, r in sorted(self.t.rows.items())
                if all(r.get(c) == v for c, v in self.filters)]

    def execute(self):
        t = self.t
        if self.op == "select":
            t.n_reads += 1
            if t.fail_reads or (t.reads_before_failure is not None
                                and t.n_reads > t.reads_before_failure):
                raise ConnectionError("supabase unreachable (read)")
            if t.rls_hidden:
                return SimpleNamespace(data=[])  # RLS without a policy: no rows, no error
            rows = [dict(t.rows[e]) for e in self._matching()]
            if self.rng:
                rows = rows[self.rng[0]:self.rng[1] + 1]
            cap = t.max_rows if self.lim is None else min(self.lim, t.max_rows)
            return SimpleNamespace(data=rows[:cap])
        t.n_writes += 1
        if t.on_write:
            hook, t.on_write = t.on_write, None
            hook()
        if t.rls_hidden:
            raise PermissionError("new row violates row-level security policy (42501)")
        if t.fail_next_writes > 0:
            t.fail_next_writes -= 1
            raise ConnectionError("supabase unreachable (write)")
        if t.fail_writes:
            raise ConnectionError("supabase unreachable (write)")
        if self.op == "upsert":
            for r in self.payload:  # Postgres checks every row before writing any
                if r["email"] in t.reject:
                    raise ValueError(f"row rejected: {r['email']}")
                datetime.fromisoformat(r["unsubscribed_at"].replace("Z", "+00:00"))  # timestamptz
            for r in self.payload:
                if not (self.ignore_duplicates and r["email"] in t.rows):
                    t.rows[r["email"]] = dict(r)
            return SimpleNamespace(data=self.payload)
        return SimpleNamespace(data=[t.rows.pop(e) for e in self._matching()])  # delete


# ── Fixtures ────────────────────────────────────────────────────────────────

_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY",
        "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
        "RAILWAY_VOLUME_MOUNT_PATH", "SITEBOOST_SUPPRESSIONS_PATH",
        "SITEBOOST_REQUIRE_DURABLE_SUPPRESSIONS")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test: file in tmp, no Railway/Supabase env, Supabase never reachable,
    no retry sleeps, fresh process state, and no background threads.

    Returns .table_calls (Supabase calls made while NOT configured: must stay
    empty) and .timers (background-retry delays armed; nothing runs by itself).
    """
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cold_outreach, "SUPPRESSIONS_PATH", tmp_path / "suppressions.json")
    for name, value in (("_last_db_error", ""), ("_backfilled", False), ("_pending", {}),
                        ("_sync_timer", None), ("_db", None), ("_DB_RETRY_DELAYS_S", (0, 0))):
        monkeypatch.setattr(cold_outreach, name, value)
    state = SimpleNamespace(table_calls=[], timers=[])

    def _unconfigured_table():
        state.table_calls.append("_table")
        raise AssertionError("Supabase used while not configured")

    def _record_timer(delay):  # stands in for threading.Timer
        state.timers.append(delay)
        cold_outreach._sync_timer = f"armed for {delay}s"

    monkeypatch.setattr(cold_outreach, "_table", _unconfigured_table)
    monkeypatch.setattr(cold_outreach, "_arm_sync", _record_timer)
    return state


@pytest.fixture
def db(monkeypatch):
    """Supabase configured and migrated (probe row present), backed by FakeTable."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")
    fake = FakeTable()
    fake.rows[PROBE] = {"email": PROBE, "unsubscribed_at": "2026-01-01T00:00:00Z", "via": "probe"}
    monkeypatch.setattr(cold_outreach, "_table", fake)
    return fake


RECIPIENTS = ("a@biz.example", "b@biz.example", "c@biz.example")


@pytest.fixture
def batch(tmp_path, monkeypatch):
    """A confirmed, live 3-recipient send; Instantly replaced by a recorder."""
    from core import siteboost_instantly
    monkeypatch.setenv("INSTANTLY_API_KEY", "test-key")
    monkeypatch.setenv("INSTANTLY_CAMPAIGN_ID", "test-campaign")
    monkeypatch.setattr(siteboost_instantly, "ACTIVE_PATH", tmp_path / "no-active-campaign.json")
    monkeypatch.setattr(cold_outreach.time, "sleep", lambda s: None)
    sent: list[str] = []

    def _fake_instantly(seq, campaign_id, key):
        sent.append(seq["to_email"])
        return {"status": 200, "body": ""}

    monkeypatch.setattr(cold_outreach, "_instantly_send_sequence", _fake_instantly)
    path = tmp_path / "04-sequences.json"
    path.write_text(json.dumps({
        "_meta": {"outbound_domain": "hello.wheellsverse.com"},
        "sequences": [{"to_email": e, "to_name": "", "touches": []} for e in RECIPIENTS],
    }))
    return SimpleNamespace(
        run=lambda: cold_outreach.send_sequences(path, confirm=True, live=True),
        sent=sent,
    )


def _file() -> dict:
    return json.loads(cold_outreach.SUPPRESSIONS_PATH.read_text())


def _write_file(entries: dict) -> None:
    cold_outreach.SUPPRESSIONS_PATH.write_text(json.dumps(entries))


# ── Normalization ───────────────────────────────────────────────────────────

class TestNormalization:
    def test_add_stores_lowercased_trimmed_in_both_stores(self, db):
        result = add_suppression("  Jane.Doe@Example.COM \n", via="click")
        assert result == {"email": "jane.doe@example.com", "file": True, "db": True, "db_error": ""}
        assert list(_file()) == ["jane.doe@example.com"]
        assert db.emails() == ["jane.doe@example.com"]
        assert db.rows["jane.doe@example.com"]["via"] == "click"

    def test_lookup_ignores_case_and_whitespace(self):
        add_suppression("Jane@Example.com")
        assert is_suppressed("  JANE@example.COM ")
        assert not is_suppressed("other@example.com")
        assert not is_suppressed("")

    def test_legacy_unnormalized_file_keys_still_match(self):
        _write_file({" Old@Example.com": {"unsubscribed_at": "2026-06-01T00:00:00Z", "via": "click"}})
        assert is_suppressed("old@example.com")
        assert [s["email"] for s in list_suppressions()] == ["old@example.com"]
        assert remove_suppression("OLD@example.com") is True
        assert not is_suppressed("old@example.com")


# ── Union reads ─────────────────────────────────────────────────────────────

class TestUnion:
    def test_reads_return_union_of_file_and_supabase(self, db):
        _write_file({"file-only@biz.example": {"unsubscribed_at": "2026-06-01T00:00:00Z", "via": "manual"}})
        db.rows["db-only@biz.example"] = {"email": "db-only@biz.example",
                                          "unsubscribed_at": "2026-07-01T00:00:00Z", "via": "click"}
        assert is_suppressed("file-only@biz.example")
        assert is_suppressed("db-only@biz.example")
        assert not is_suppressed("neither@biz.example")
        assert {s["email"] for s in list_suppressions()} == {"file-only@biz.example",
                                                              "db-only@biz.example"}

    def test_optout_survives_container_wipe(self, db):
        add_suppression("gone@biz.example")
        cold_outreach.SUPPRESSIONS_PATH.unlink()  # a redeploy wipes the container file
        assert is_suppressed("gone@biz.example")
        assert [s["email"] for s in list_suppressions()] == ["gone@biz.example"]

    def test_list_reads_every_page_despite_server_row_cap(self, db):
        db.max_rows = 2
        for i in range(5):
            e = f"p{i}@biz.example"
            db.rows[e] = {"email": e, "unsubscribed_at": f"2026-07-0{i + 1}T00:00:00Z", "via": "click"}
        assert len(list_suppressions()) == 5

    def test_db_read_failure_falls_back_to_file_outside_send_path(self, db):
        add_suppression("in-file@biz.example")
        db.rows["db-only@biz.example"] = {"email": "db-only@biz.example",
                                          "unsubscribed_at": "", "via": "click"}
        db.fail_reads = True
        assert is_suppressed("in-file@biz.example")           # lenient: file answer
        assert not is_suppressed("db-only@biz.example")
        with pytest.raises(SuppressionStoreError):              # strict: the send path stops
            is_suppressed("db-only@biz.example", strict=True)
        assert {s["email"] for s in list_suppressions()} == {"in-file@biz.example"}

    def test_probe_row_is_hidden_and_cannot_be_removed(self, db):
        add_suppression("a@biz.example")
        assert [s["email"] for s in list_suppressions()] == ["a@biz.example"]
        with pytest.raises(ValueError):
            remove_suppression(PROBE)
        assert PROBE in db.rows


# ── Dual write ──────────────────────────────────────────────────────────────

class TestDualWrite:
    def test_db_write_failure_keeps_file_entry_and_is_visible(self, db, caplog):
        db.fail_writes = True
        with caplog.at_level(logging.ERROR, logger="cold_outreach"):
            result = add_suppression("x@biz.example", via="click")
        assert result["file"] is True and result["db"] is False
        assert "unreachable" in result["db_error"]
        assert "x@biz.example" in _file()
        assert db.emails() == []
        assert any(r.levelno == logging.ERROR and "x@biz.example" in r.getMessage()
                   for r in caplog.records)
        assert is_suppressed("x@biz.example")
        st = suppression_store_status()  # health shows it
        assert st["pending"] == 1 and st["db_error"]

        db.fail_writes = False           # Supabase recovers
        st = suppression_store_status()  # → retried while anything is pending
        assert "x@biz.example" in db.rows
        assert st["pending"] == 0 and st["db_error"] == ""

    def test_supabase_write_is_retried_inline(self, db):
        db.fail_next_writes = 2  # the 3rd try lands
        result = add_suppression("blip@biz.example")
        assert result["db"] is True and result["db_error"] == ""
        assert db.emails() == ["blip@biz.example"]
        assert cold_outreach._pending == {}

    def test_add_is_idempotent_and_keeps_the_first_record(self, db):
        add_suppression("x@biz.example", via="click")
        first_db, first_file = dict(db.rows["x@biz.example"]), _file()["x@biz.example"]
        add_suppression(" X@biz.example", via="manual")
        assert db.rows["x@biz.example"] == first_db
        assert _file()["x@biz.example"] == first_file

    def test_raises_when_no_store_recorded_the_optout(self, db, monkeypatch, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setattr(cold_outreach, "SUPPRESSIONS_PATH", blocker / "suppressions.json")
        db.fail_writes = True
        with pytest.raises(RuntimeError, match="NOT recorded"):
            add_suppression("lost@biz.example")

    def test_file_write_failure_is_ok_when_supabase_has_it(self, db, monkeypatch, tmp_path):
        # e.g. `railway run`: SITEBOOST_SUPPRESSIONS_PATH points at a volume not mounted here
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setattr(cold_outreach, "SUPPRESSIONS_PATH", blocker / "suppressions.json")
        result = add_suppression("saved@biz.example")
        assert result["file"] is False and result["db"] is True
        assert is_suppressed("saved@biz.example")


# ── Retry until durable ─────────────────────────────────────────────────────

class TestRetry:
    def test_failed_write_is_retried_in_background_until_it_lands(self, db, isolated):
        db.fail_writes = True
        add_suppression("x@biz.example")
        add_suppression("y@biz.example")
        assert isolated.timers == [30]  # one timer per process, not one per failure

        for _ in range(6):              # Supabase stays down: back off, capped at 15 min
            cold_outreach._sync_step(isolated.timers[-1])
        assert isolated.timers == [30, 60, 120, 240, 480, 900, 900]
        assert cold_outreach._pending.keys() == {"x@biz.example", "y@biz.example"}

        db.fail_writes = False          # Supabase recovers: the next retry lands it all
        cold_outreach._sync_step(isolated.timers[-1])
        assert db.emails() == ["x@biz.example", "y@biz.example"]
        assert len(isolated.timers) == 7 and cold_outreach._sync_timer is None  # loop stopped
        st = suppression_store_status()
        assert st["pending"] == 0 and st["db_error"] == ""

    def test_repeat_click_retries_a_write_that_only_reached_the_file(self, db):
        db.fail_writes = True
        add_suppression("x@biz.example")
        db.fail_writes = False
        assert add_suppression("x@biz.example")["db"] is True  # what /u/{token} does again
        assert db.emails() == ["x@biz.example"]
        assert cold_outreach._pending == {}

    def test_backfill_clears_only_what_it_wrote(self, db, isolated):
        # A backfill reads the file; while it writes, a click's Supabase write fails.
        # That opt-out wasn't in the backfill's snapshot, so it must stay pending.
        _write_file({"old@biz.example": {"unsubscribed_at": "2026-06-01T00:00:00Z", "via": "click"}})
        db.reject = {"new@biz.example"}
        db.on_write = lambda: add_suppression("new@biz.example")
        assert backfill_suppressions()["ok"] is True
        assert db.emails() == ["old@biz.example"]
        assert cold_outreach._pending.keys() == {"new@biz.example"}
        assert suppression_store_status()["db_error"]

        db.reject = set()
        cold_outreach._sync_step(isolated.timers[-1])
        assert db.emails() == ["new@biz.example", "old@biz.example"]
        assert suppression_store_status()["pending"] == 0

    def test_one_bad_row_does_not_hold_back_the_rest(self, db):
        _write_file({e: {"unsubscribed_at": "2026-06-01T00:00:00Z", "via": "click"} for e in RECIPIENTS})
        db.reject = {"b@biz.example"}
        result = backfill_suppressions()
        assert result["ok"] is False and result["pending"] == 1
        assert db.emails() == ["a@biz.example", "c@biz.example"]
        assert cold_outreach._pending.keys() == {"b@biz.example"}

    def test_outage_stops_the_backfill_early(self, db):
        _write_file({f"r{i}@biz.example": {"unsubscribed_at": "2026-06-01T00:00:00Z", "via": "click"}
                     for i in range(10)})
        db.fail_writes = True
        result = backfill_suppressions()
        assert result["ok"] is False and result["pending"] == 10
        assert db.n_writes == 4  # the chunk + 3 single rows, not one call per row

    def test_unparseable_timestamp_is_replaced_not_rejected(self, db):
        _write_file({"odd@biz.example": {"unsubscribed_at": "not-a-date", "via": "manual"}})
        assert backfill_suppressions()["ok"] is True
        at = db.rows["odd@biz.example"]["unsubscribed_at"]
        assert datetime.fromisoformat(at.replace("Z", "+00:00")).year >= 2026


# ── Remove ──────────────────────────────────────────────────────────────────

class TestRemove:
    def test_remove_deletes_from_both_stores(self, db):
        add_suppression("a@biz.example")
        assert remove_suppression("  A@Biz.example ") is True
        assert "a@biz.example" not in _file()
        assert "a@biz.example" not in db.rows
        assert not is_suppressed("a@biz.example")
        assert remove_suppression("a@biz.example") is False

    def test_remove_finds_supabase_only_entry(self, db):
        db.rows["b@biz.example"] = {"email": "b@biz.example", "unsubscribed_at": "", "via": "manual"}
        assert remove_suppression("b@biz.example") is True
        assert db.emails() == []

    def test_failed_supabase_delete_leaves_address_suppressed(self, db):
        add_suppression("keep@biz.example")
        db.fail_writes = True
        with pytest.raises(SuppressionStoreError):
            remove_suppression("keep@biz.example")
        assert "keep@biz.example" in _file()
        assert "keep@biz.example" in db.rows


# ── Backfill ────────────────────────────────────────────────────────────────

class TestBackfill:
    def test_backfill_is_idempotent_and_keeps_existing_rows(self, db):
        _write_file({
            "a@biz.example": {"unsubscribed_at": "2026-08-01T00:00:00Z", "via": "manual"},
            "b@biz.example": {"unsubscribed_at": "2026-08-02T00:00:00Z", "via": "click"},
        })
        original = {"email": "a@biz.example", "unsubscribed_at": "2026-06-01T00:00:00Z", "via": "click"}
        db.rows["a@biz.example"] = dict(original)

        first = backfill_suppressions()
        assert first == {"ok": True, "n": 2, "error": "", "pending": 0}
        assert db.rows["a@biz.example"] == original  # first opt-out record is kept
        assert db.rows["b@biz.example"]["via"] == "click"

        snapshot = copy.deepcopy(db.rows)
        assert backfill_suppressions() == first
        assert db.rows == snapshot

    def test_backfill_runs_lazily_on_first_good_contact(self, db):
        _write_file({"pre-db@biz.example": {"unsubscribed_at": "2026-06-01T00:00:00Z", "via": "click"}})
        assert db.emails() == []
        suppression_store_status()
        assert "pre-db@biz.example" in db.rows

    def test_backfill_without_supabase_is_a_noop(self, isolated):
        add_suppression("local@biz.example")
        assert backfill_suppressions()["ok"] is False
        assert isolated.table_calls == [] and isolated.timers == []


# ── Fail closed (send path) ─────────────────────────────────────────────────

class TestFailClosed:
    @pytest.mark.parametrize("var", ["RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME",
                                     "RAILWAY_PROJECT_ID"])
    def test_railway_without_supabase_refuses_to_send(self, batch, monkeypatch, var):
        monkeypatch.setenv(var, "production")
        result = batch.run()
        assert result["status"] == "blocked"
        assert "durable" in result["reason"]
        assert batch.sent == []

    def test_explicit_flag_refuses_to_send_without_supabase(self, batch, monkeypatch):
        monkeypatch.setenv("SITEBOOST_REQUIRE_DURABLE_SUPPRESSIONS", "1")
        assert batch.run()["status"] == "blocked"
        assert batch.sent == []

    @pytest.mark.parametrize("mounted", [True, False])
    def test_volume_file_counts_only_in_the_web_container(self, batch, monkeypatch, tmp_path, mounted):
        mount = tmp_path / "vol"
        path = mount / "siteboost" / "suppressions.json"
        monkeypatch.setattr(cold_outreach, "SUPPRESSIONS_PATH", path)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        monkeypatch.setenv("SITEBOOST_SUPPRESSIONS_PATH", str(path))
        monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(mount))
        # mounted=False is `railway run` on the operator's machine: same env, no volume
        monkeypatch.setattr(cold_outreach.os.path, "ismount", lambda p: mounted and Path(p) == mount)
        add_suppression("b@biz.example")
        result = batch.run()
        if mounted:
            assert result["status"] == "ok"
            assert batch.sent == ["a@biz.example", "c@biz.example"]
        else:
            assert result["status"] == "blocked"
            assert batch.sent == []

    def test_supabase_unreadable_refuses_whole_batch(self, db, batch):
        db.fail_reads = True
        result = batch.run()
        assert result["status"] == "blocked"
        assert "can't be read" in result["reason"]
        assert batch.sent == []

    def test_key_without_service_role_refuses_to_send(self, db, batch, monkeypatch):
        # RLS with no policy answers a non-service key with [] instead of an error,
        # so this opt-out would look absent: the probe row catches it.
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        db.rows["b@biz.example"] = {"email": "b@biz.example",
                                    "unsubscribed_at": "2026-07-01T00:00:00Z", "via": "click"}
        db.rls_hidden = True
        result = batch.run()
        assert result["status"] == "blocked"
        assert "service_role" in result["reason"]
        assert batch.sent == []

    def test_supabase_read_failure_mid_batch_stops(self, db, batch):
        db.reads_before_failure = 2  # store check + first recipient succeed
        result = batch.run()
        assert result["status"] == "stopped"
        assert batch.sent == ["a@biz.example"]
        assert "b@biz.example" in result["reason"]

    def test_web_optout_is_honored_by_railway_run_sender(self, db, batch, monkeypatch):
        # Clicked on the web app; this machine's file has never seen it.
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        db.rows["b@biz.example"] = {"email": "b@biz.example",
                                    "unsubscribed_at": "2026-07-01T00:00:00Z", "via": "click"}
        result = batch.run()
        assert result["status"] == "ok"
        assert batch.sent == ["a@biz.example", "c@biz.example"]
        assert result["n_suppressed"] == 1
        assert result["suppression_store"] == "supabase+file"
        assert result["warning"] == ""

    def test_optout_after_compose_is_honored_at_send_time(self, batch):
        add_suppression("c@biz.example")
        assert batch.run()["status"] == "ok"
        assert batch.sent == ["a@biz.example", "b@biz.example"]

    def test_local_dev_keeps_file_only_behavior(self, batch, isolated):
        add_suppression("a@biz.example")
        st = suppression_store_status()
        assert st["store"] == "file" and st["ok"] is True and st["durable"] is False
        result = batch.run()
        assert result["status"] == "ok"
        assert batch.sent == ["b@biz.example", "c@biz.example"]
        assert "railway run" in result["warning"]  # but it says web opt-outs aren't checked
        assert isolated.table_calls == [] and isolated.timers == []  # Supabase never touched


# ── Public unsubscribe endpoint (/u/{token}) ────────────────────────────────

@pytest.fixture(scope="module")
def api():
    """core.api, imported before the per-test env cleanup (it loads .env on import)."""
    pytest.importorskip("fastapi")
    from core import api as api_module
    return api_module


class TestUnsubscribeEndpoint:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch, tmp_path):
        from core import siteboost_events
        monkeypatch.setenv("SITEBOOST_UNSUBSCRIBE_SECRET", "test-secret")
        monkeypatch.setattr(siteboost_events, "EVENTS_PATH", tmp_path / "events.jsonl")

    @staticmethod
    def _click(api, email):
        return api.siteboost_unsubscribe(cold_outreach.make_unsubscribe_token(email))

    def test_handler_runs_in_the_threadpool(self, api):
        # async def would run its blocking Supabase calls on the event loop
        assert not inspect.iscoroutinefunction(api.siteboost_unsubscribe)

    def test_repeat_click_retries_supabase(self, api, db):
        db.fail_writes = True
        r = self._click(api, "x@biz.example")
        assert r.status_code == 200 and "x@biz.example" in _file()
        assert db.emails() == []
        db.fail_writes = False
        r = self._click(api, "x@biz.example")
        assert r.status_code == 200 and b"already" in r.body
        assert db.emails() == ["x@biz.example"]

    def test_unrecorded_optout_is_not_confirmed(self, api, db, monkeypatch, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setattr(cold_outreach, "SUPPRESSIONS_PATH", blocker / "suppressions.json")
        db.fail_writes = True
        r = self._click(api, "lost@biz.example")
        assert r.status_code == 503
        assert b"reply STOP" in r.body

    def test_startup_arms_the_background_sync(self, api, db, isolated):
        assert api._siteboost_suppression_sync in api._DEFERRED_STARTUP_HANDLERS
        api._siteboost_suppression_sync()
        assert isolated.timers == [0]


# ── Admin health check ──────────────────────────────────────────────────────

class TestHealthCheck:
    def _suppression_axis(self, monkeypatch) -> dict:
        pytest.importorskip("fastapi")
        import socket
        from narai.api.routes import siteboost_admin
        monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")  # no DNS
        checks = siteboost_admin.launch_readiness(_=True)["checks"]
        return next(c for c in checks if c["axis"] == "suppression")

    def test_reports_durable_supabase_store(self, db, monkeypatch):
        axis = self._suppression_axis(monkeypatch)
        assert axis["status"] == "ok"
        assert "supabase+file" in axis["detail"] and "durable" in axis["detail"]

    def test_warns_while_an_optout_is_not_in_supabase(self, db, monkeypatch):
        db.fail_writes = True
        add_suppression("x@biz.example")
        axis = self._suppression_axis(monkeypatch)
        assert axis["status"] == "warn"
        assert "1 opt-out(s) only in this container's file" in axis["detail"]
        assert "0 pending" in axis["action"]

    def test_fails_on_railway_without_durable_store(self, monkeypatch):
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        axis = self._suppression_axis(monkeypatch)
        assert axis["status"] == "fail"
        assert "NOT durable" in axis["detail"]
        assert "0001_siteboost_suppressions.sql" in axis["action"]
