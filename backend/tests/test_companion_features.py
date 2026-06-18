"""Relationship engine + daily check-in + voice journal — unit tests (temp DBs)."""
import pytest

from app.services.relationship import storage as rel
from app.services.relationship.injection import relationship_preamble
from app.services.checkin import storage as ckstore
from app.services.checkin import scheduler as cksched
from app.services.checkin import composer as ckcomposer
from app.services.journal import storage as jstore
from app.services.journal import service as jservice


@pytest.fixture(autouse=True)
def _temp_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "REL_DB_PATH", tmp_path / "rel.db")
    monkeypatch.setattr(ckstore, "CHECKIN_DB_PATH", tmp_path / "checkin.db")
    monkeypatch.setattr(jstore, "JOURNAL_DB_PATH", tmp_path / "journal.db")
    for v in ("KAI_SCOPE_RELATIONSHIP", "KAI_SCOPE_CHECKIN",
              "KAI_CHECKIN_SCHEDULER_ENABLED"):
        monkeypatch.delenv(v, raising=False)
    yield


# ─── relationship engine ───────────────────────────────────────────────
def test_state_defaults_and_interaction():
    s = rel.get_state()
    assert s["interaction_count"] == 0 and s["trust_score"] == 50
    rel.record_interaction(); rel.record_interaction()
    s = rel.get_state()
    assert s["interaction_count"] == 2
    assert s["familiarity_score"] == rel.familiarity_from_count(2)


def test_trust_clamps():
    assert rel.adjust_trust(100) == 100      # clamps at 100
    assert rel.adjust_trust(-500) == 0       # clamps at 0


def test_milestone_win_bumps_trust():
    before = rel.get_state()["trust_score"]
    m = rel.add_milestone("shipped Sol Phase 2", "win")
    assert m.kind == "win"
    assert rel.get_state()["trust_score"] == before + 2
    assert len(rel.list_milestones()) == 1


def test_bad_milestone_kind_rejected():
    with pytest.raises(ValueError):
        rel.add_milestone("x", "not_a_kind")


def test_relationship_injection_scope_gate(monkeypatch):
    rel.record_interaction()
    assert relationship_preamble() == ""           # scope off
    monkeypatch.setenv("KAI_SCOPE_RELATIONSHIP", "1")
    out = relationship_preamble()
    assert "RELATIONSHIP" in out and "conversations" in out


def test_relationship_injection_quiet_when_nothing_earned(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_RELATIONSHIP", "1")
    assert relationship_preamble() == ""           # 0 interactions, no milestones


# ─── daily check-in ────────────────────────────────────────────────────
def test_compose_checkin_is_warm():
    msg = ckcomposer.compose_checkin()
    assert "Good morning" in msg and "feeling today" in msg


def test_checkin_idempotent_per_day():
    first = ckstore.record_checkin("20260617", "hi", True)
    assert first is not None
    dup = ckstore.record_checkin("20260617", "hi again", True)
    assert dup is None                              # UNIQUE date_key
    assert ckstore.has_checkin("20260617") is True


def test_run_checkin_dedups_only_after_real_delivery(monkeypatch):
    # Synchronous boolean sender (real delivery), not fire-and-forget notify().
    monkeypatch.setattr("app.services.supreme.scanner.telegram_send", lambda *a, **k: True)
    r1 = cksched.run_checkin()
    assert r1["sent"] is True and r1["already_done"] is False and r1["message"]
    r2 = cksched.run_checkin()                       # delivered today → done
    assert r2["already_done"] is True and r2["sent"] is False
    r3 = cksched.run_checkin(force=True)             # force re-sends
    assert r3["sent"] is True and r3["already_done"] is False


def test_run_checkin_failed_delivery_is_not_fabricated_and_retries(monkeypatch):
    # The HIGH bug: a failed send must report sent=False (not fabricated True) and
    # must remain retryable (not silently recorded as done).
    calls = {"n": 0}
    def flaky_send(*a, **k):
        calls["n"] += 1
        return calls["n"] >= 2                        # first send fails, second succeeds
    monkeypatch.setattr("app.services.supreme.scanner.telegram_send", flaky_send)
    r1 = cksched.run_checkin()
    assert r1["sent"] is False and r1["already_done"] is False   # NOT fabricated
    row = ckstore.recent(1)[0]
    assert row.sent is False                          # recorded the TRUE (failed) outcome
    r2 = cksched.run_checkin()                        # retries the undelivered day
    assert r2["sent"] is True and r2["already_done"] is False


def test_checkin_scheduler_status():
    st = cksched.status()
    assert set(st) >= {"enabled", "running", "hour_utc", "scope_on"}
    assert st["enabled"] is False                   # opt-in, off by default


# ─── voice journal ─────────────────────────────────────────────────────
def test_journal_create_without_router_truncates():
    out = jservice.create_journal_entry(
        "Today was rough, I'm exhausted and burned out from the launch.",
        router=None, store_to_memory=False,
    )
    e = out["entry"]
    assert e["mood"] == "tired"                      # detected from text
    assert e["summary"]                              # fallback truncation, non-empty
    assert out["memory_saved"] is False             # no session given


def test_journal_empty_rejected():
    with pytest.raises(ValueError):
        jservice.create_journal_entry("   ", router=None, store_to_memory=False)


def test_journal_history_and_stats():
    jservice.create_journal_entry("feeling great today!", router=None, store_to_memory=False)
    jservice.create_journal_entry("so stressed, too much to do", router=None, store_to_memory=False)
    assert jstore.stats()["total_entries"] == 2
    rows = jstore.recent(limit=10)
    assert len(rows) == 2 and rows[0].created_at  # newest first
