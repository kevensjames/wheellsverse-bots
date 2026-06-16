"""Sol ROSCA engine — state-machine invariants over an isolated temp ledger.

Pure logic: no Dwolla, no mocking. Each test runs against its own sqlite file.
"""
import importlib

import pytest

from app.services.sol import storage as st
from app.services.sol import engine


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    # Point the ledger at a fresh per-test sqlite file and re-init the schema.
    monkeypatch.setattr(st, "SOL_DB_PATH", tmp_path / "sol.db")
    st.init_db()
    monkeypatch.setattr(engine, "MAX_RETRIES", 2)
    yield


def _funded_circle(n=3, contribution_cents=20000):
    c = engine.create_circle("Test Circle", contribution_cents, n)
    for i in range(n):
        engine.add_member(c.id, f"M{i}", email=f"m{i}@x.com",
                          dwolla_customer_id=f"cust-{i}",
                          funding_source_href=f"https://api-sandbox.dwolla.com/funding-sources/fs-{i}")
    return c


def _drive_to_delinquent(cid):
    """Walk a contribution through the full fail→retry ladder to delinquency:
    fail (rc0) → retry (rc1) → fail (rc1) → retry (rc2) → fail (rc2 ≥ MAX)."""
    engine.mark_contribution_result(cid, False)
    for _ in range(engine.MAX_RETRIES):
        engine.record_retry(cid)
        engine.mark_contribution_result(cid, False)


# ─── circle formation ────────────────────────────────────────────────
def test_add_member_rejects_when_full():
    c = _funded_circle(n=2)
    with pytest.raises(engine.SolStateError):
        engine.add_member(c.id, "overflow")


def test_activate_requires_full_roster():
    c = engine.create_circle("c", 20000, 3)
    engine.add_member(c.id, "only", dwolla_customer_id="x", funding_source_href="y")
    with pytest.raises(engine.SolStateError):
        engine.activate_circle(c.id)


def test_activate_requires_all_funded():
    c = engine.create_circle("c", 20000, 2)
    engine.add_member(c.id, "funded", dwolla_customer_id="x", funding_source_href="y")
    engine.add_member(c.id, "unfunded")  # no funding source
    with pytest.raises(engine.SolStateError):
        engine.activate_circle(c.id)


def test_activate_assigns_positions_and_opens_cycle_one():
    c = _funded_circle(n=3, contribution_cents=20000)
    out = engine.activate_circle(c.id)
    assert out["circle"]["status"] == "active"
    members = st.list_members(c.id)
    assert sorted(m.join_order for m in members) == [1, 2, 3]
    assert all(m.status == "active" for m in members)
    # cycle 1 opened, recipient = position 1, one contribution per member
    assert out["cycle"]["cycle_number"] == 1
    pos1 = next(m for m in members if m.join_order == 1)
    assert out["cycle"]["recipient_member_id"] == pos1.id
    assert len(out["contributions"]) == 3
    assert all(ct["amount_cents"] == 20000 and ct["status"] == "pending"
               for ct in out["contributions"])


# ─── collection majority math ──────────────────────────────────────────
def test_majority_threshold_and_met():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    contribs = st.list_contributions(cyc["id"])
    # 1 of 3 processed → majority not met (threshold = 2)
    engine.mark_contribution_result(contribs[0].id, True)
    s = engine.collection_status(cyc["id"])
    assert s["majority_threshold"] == 2 and s["majority_met"] is False
    # 2 of 3 processed → majority met
    engine.mark_contribution_result(contribs[1].id, True)
    s = engine.collection_status(cyc["id"])
    assert s["majority_met"] is True
    assert s["processed_cents"] == 40000


def test_payout_blocked_until_majority():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    with pytest.raises(engine.SolStateError):
        engine.close_collection_and_create_payout(cyc["id"])


def test_payout_equals_collected_pool_no_defaulter_coverage():
    # 3-member circle, contribution 200.00; member 3 never pays → pool = 400.00.
    c = _funded_circle(n=3, contribution_cents=20000)
    cyc = engine.activate_circle(c.id)["cycle"]
    contribs = st.list_contributions(cyc["id"])
    engine.mark_contribution_result(contribs[0].id, True)
    engine.mark_contribution_result(contribs[1].id, True)
    out = engine.close_collection_and_create_payout(cyc["id"])
    assert out["payout"]["amount_cents"] == 40000  # NOT 60000 — no one covers
    assert st.get_cycle(cyc["id"]).status == "collected"


def test_payout_is_idempotent():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    contribs = st.list_contributions(cyc["id"])
    engine.mark_contribution_result(contribs[0].id, True)
    engine.mark_contribution_result(contribs[1].id, True)
    p1 = engine.close_collection_and_create_payout(cyc["id"])
    p2 = engine.close_collection_and_create_payout(cyc["id"])
    assert p2["already_staged"] is True
    assert p1["payout"]["id"] == p2["payout"]["id"]


# ─── delinquency ladder ────────────────────────────────────────────────
def test_retry_ladder_then_delinquent():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    cid = st.list_contributions(cyc["id"])[2].id
    # fail #1 (retry_count 0 < 2): not delinquent
    assert engine.mark_contribution_result(cid, False)["member_delinquent"] is False
    engine.record_retry(cid)  # retry_count → 1
    assert engine.mark_contribution_result(cid, False)["member_delinquent"] is False
    engine.record_retry(cid)  # retry_count → 2
    # fail at retry_count 2 (>= MAX_RETRIES) → delinquent
    assert engine.mark_contribution_result(cid, False)["member_delinquent"] is True
    member_id = st.get_contribution(cid).member_id
    assert st.get_member(member_id).status == "delinquent"
    # further retries refused
    with pytest.raises(engine.SolStateError):
        engine.record_retry(cid)


def test_delinquent_member_excluded_from_next_cycle():
    c = _funded_circle(n=3)
    engine.activate_circle(c.id)
    cyc1 = st.list_cycles(c.id)[0]
    contribs = st.list_contributions(cyc1.id)
    # pay 1 & 2; member 3 defaults to delinquent
    engine.mark_contribution_result(contribs[0].id, True)
    engine.mark_contribution_result(contribs[1].id, True)
    _drive_to_delinquent(contribs[2].id)  # member 3 delinquent
    # finish cycle 1
    engine.close_collection_and_create_payout(cyc1.id)
    payout = st.get_payout_for_cycle(cyc1.id)
    engine.mark_payout_result(payout.id, True)
    # advance → cycle 2 has only the 2 active members contributing
    nxt = engine.advance_circle(c.id)
    assert len(nxt["contributions"]) == 2


def test_recipient_delinquent_gets_no_payout():
    # 3 members; the position-1 recipient goes delinquent before payout.
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    members = {m.join_order: m for m in st.list_members(c.id)}
    contribs = {ct.member_id: ct for ct in st.list_contributions(cyc["id"])}
    recip_cid = contribs[members[1].id].id
    _drive_to_delinquent(recip_cid)  # the position-1 recipient defaults
    # the other two pay → majority met
    engine.mark_contribution_result(contribs[members[2].id].id, True)
    engine.mark_contribution_result(contribs[members[3].id].id, True)
    out = engine.close_collection_and_create_payout(cyc["id"])
    assert out["payout"] is None and out["recipient_delinquent"] is True
    # ROLLOVER POLICY: the forfeited pool accumulates on the circle.
    assert out["rolled_into_next_cents"] == 40000
    assert out["circle_rollover_cents"] == 40000
    assert st.get_circle(c.id).rollover_cents == 40000


def test_forfeited_pool_rolls_into_next_payout():
    # Cycle 1 recipient (pos 1) forfeits; cycle 2 recipient (pos 2) gets the
    # cycle-2 pool PLUS the rolled-forward cycle-1 pool.
    c = _funded_circle(n=3, contribution_cents=20000)
    cyc1 = engine.activate_circle(c.id)["cycle"]
    members = {m.join_order: m for m in st.list_members(c.id)}
    contribs1 = {ct.member_id: ct for ct in st.list_contributions(cyc1["id"])}
    _drive_to_delinquent(contribs1[members[1].id].id)             # pos-1 recipient forfeits
    engine.mark_contribution_result(contribs1[members[2].id].id, True)
    engine.mark_contribution_result(contribs1[members[3].id].id, True)
    out1 = engine.close_collection_and_create_payout(cyc1["id"])
    assert out1["payout"] is None
    assert st.get_circle(c.id).rollover_cents == 40000

    # advance past the forfeit cycle → cycle 2 (recipient pos 2, pos-1 excluded)
    nxt = engine.advance_circle(c.id)
    cyc2 = nxt["cycle"]
    assert len(nxt["contributions"]) == 2  # pos 1 delinquent, excluded
    for ct in st.list_contributions(cyc2["id"]):
        engine.mark_contribution_result(ct.id, True)            # 2 × 200 = 400 collected
    out2 = engine.close_collection_and_create_payout(cyc2["id"])
    # payout = cycle-2 pool (40000) + rolled-forward cycle-1 pool (40000)
    assert out2["payout"]["amount_cents"] == 80000
    assert out2["applied_rollover_cents"] == 40000
    # accumulator stays until the payout TRANSFER settles (deferred clearing)
    assert st.get_circle(c.id).rollover_cents == 40000
    engine.mark_payout_result(out2["payout"]["id"], True)
    assert st.get_circle(c.id).rollover_cents == 0  # cleared on payout success


def test_scan_due_actions_reports_collect_payout_advance():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    # fresh cycle → collect_due
    acts = engine.scan_due_actions()
    assert any(a["action"] == "collect_due" and a["circle_id"] == c.id for a in acts)
    # majority clears → payout_ready also surfaces
    contribs = st.list_contributions(cyc["id"])
    engine.mark_contribution_result(contribs[0].id, True)
    engine.mark_contribution_result(contribs[1].id, True)
    acts = engine.scan_due_actions()
    assert any(a["action"] == "payout_ready" for a in acts)
    # pay + (don't advance) → advance_ready
    engine.mark_contribution_result(contribs[2].id, True)
    out = engine.close_collection_and_create_payout(cyc["id"])
    engine.mark_payout_result(out["payout"]["id"], True)
    acts = engine.scan_due_actions()
    assert any(a["action"] == "advance_ready" for a in acts)


# ─── webhook idempotency / monotonicity (review FIX B) ─────────────────
def test_mark_contribution_idempotent_on_duplicate_success():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    cid = st.list_contributions(cyc["id"])[0].id
    assert engine.mark_contribution_result(cid, True).get("noop") is not True
    out = engine.mark_contribution_result(cid, True)  # duplicate completed webhook
    assert out.get("noop") is True
    assert st.get_contribution(cid).status == "processed"


def test_return_after_completed_marks_returned():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    cid = st.list_contributions(cyc["id"])[0].id
    engine.mark_contribution_result(cid, True)          # transfer_completed
    engine.mark_contribution_result(cid, False)         # later ACH return (R01)
    assert st.get_contribution(cid).status == "returned"


def test_mark_payout_idempotent():
    c = _funded_circle(n=3)
    cyc = engine.activate_circle(c.id)["cycle"]
    cs = st.list_contributions(cyc["id"])
    engine.mark_contribution_result(cs[0].id, True)
    engine.mark_contribution_result(cs[1].id, True)
    out = engine.close_collection_and_create_payout(cyc["id"])
    pid = out["payout"]["id"]
    engine.mark_payout_result(pid, True)
    again = engine.mark_payout_result(pid, True)        # duplicate webhook
    assert again.get("noop") is True
    assert st.get_cycle(cyc["id"]).status == "paid"


# ─── payout failure preserves the pool (review FIX C) ──────────────────
def test_payout_failure_rolls_pool_forward():
    c = _funded_circle(n=3, contribution_cents=20000)
    cyc = engine.activate_circle(c.id)["cycle"]
    cs = st.list_contributions(cyc["id"])
    engine.mark_contribution_result(cs[0].id, True)
    engine.mark_contribution_result(cs[1].id, True)
    out = engine.close_collection_and_create_payout(cyc["id"])  # amount = 40000
    engine.mark_payout_result(out["payout"]["id"], False)        # ACH payout fails
    # the undelivered pool is NOT lost — it rolls forward intact
    assert st.get_circle(c.id).rollover_cents == 40000
    assert st.get_cycle(cyc["id"]).status == "failed"


# ─── full rotation to completion ───────────────────────────────────────
def test_full_two_member_rotation_completes():
    c = _funded_circle(n=2, contribution_cents=20000)
    engine.activate_circle(c.id)
    for expected_cycle in (1, 2):
        cyc = st.list_cycles(c.id)[-1]
        assert cyc.cycle_number == expected_cycle
        for ct in st.list_contributions(cyc.id):
            engine.mark_contribution_result(ct.id, True)
        engine.close_collection_and_create_payout(cyc.id)
        payout = st.get_payout_for_cycle(cyc.id)
        assert payout["amount_cents"] if isinstance(payout, dict) else payout.amount_cents == 40000
        engine.mark_payout_result(payout.id, True)
        result = engine.advance_circle(c.id)
    assert result["completed"] is True
    assert st.get_circle(c.id).status == "completed"
    # each member was paid exactly once (positions 1 and 2)
    recipients = [cy.recipient_member_id for cy in st.list_cycles(c.id)]
    assert len(set(recipients)) == 2
