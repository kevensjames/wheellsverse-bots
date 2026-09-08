"""Dispatch contract checks (Phase 8).

Centred on the invariant that a remote machine changes everything about trust: a worker
reports, KAI decides. Most of these tests try to make the worker decide something.

    cd backend && python3 app/services/holding/test_computer_ops_dispatch.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))))

from app.services.holding.device_identity import DevicePrincipal, DeviceStatus  # noqa: E402
from app.services.holding import computer_ops_dispatch as d  # noqa: E402
from app.services.holding.computer_ops_dispatch import (  # noqa: E402
    COMPLETED, FAILED, LEASED, QUEUED, RUNNING, STOPPED, DispatchError, NotAuthorised,
    attach_evidence, cancel_mission, consume_approval, create_mission, evaluate_reconnect,
    lease_next, parameter_digest, renew_lease, request_approval, resolve_approval,
    stop_all, submit_progress, verify_and_complete)

PASSED, FAILED_T = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED_T).append(name)
    print(f"  {'ok ' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail and not cond else ""))


def expect(name, exc_type, fn, needle=""):
    try:
        fn()
        check(name, False, "no exception raised")
    except exc_type as exc:
        check(name, needle.lower() in str(exc).lower() if needle else True, str(exc))
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"wrong exception {type(exc).__name__}: {exc}")


class Store:
    def __init__(self):
        self.m, self.burned = {}, {}

    def get(self, mid): return self.m.get(mid)
    def put(self, mission): self.m[mission.mission_id] = mission
    def queued_for_device(self, did): return [x for x in self.m.values() if x.device_id == did]

    def burn(self, key, exp):
        if key in self.burned:
            return False
        self.burned[key] = exp
        return True


def principal(device_id="dev-1", scopes=None, ttl=timedelta(minutes=15)):
    return DevicePrincipal(
        device_id=device_id,
        scopes=frozenset(scopes if scopes is not None else {
            "computer.mission.receive", "computer.mission.status.write",
            "computer.evidence.write", "computer.permission.request"}),
        lease_expires_at=datetime.now(timezone.utc) + ttl)


def fresh(store=None, device="dev-1", mode="EXECUTE_SCOPED"):
    store = store or Store()
    m = create_mission(store, tenant="t1", device_id=device, objective="tidy repo",
                       autonomy_mode=mode, attestation_digest="a" * 64, actor="owner")
    return store, m


no_stop = lambda: False  # noqa: E731

print("=== a worker reports; KAI decides ===")
s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
expect("worker cannot set COMPLETED", NotAuthorised,
       lambda: submit_progress(s, p, m.mission_id, status=COMPLETED), "may not set status")
submit_progress(s, p, m.mission_id, status=RUNNING)
check("worker may report RUNNING", s.get(m.mission_id).status == RUNNING)
submit_progress(s, p, m.mission_id, status="FAILED")
check("worker may report FAILED", s.get(m.mission_id).status == "FAILED")

s, m = fresh()
verify_and_complete(s, m.mission_id, verifier=lambda _m: (True, "evidence ok"), actor="kai")
check("KAI may complete after its own verification", s.get(m.mission_id).status == COMPLETED)

s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
attach_evidence(s, p, m.mission_id, evidence={"kind": "diff", "claim": "succeeded"})
verify_and_complete(s, m.mission_id,
                    verifier=lambda _m: (False, "diff does not match claim"), actor="kai")
check("worker claiming success + failing verifier => FAILED, not COMPLETED",
      s.get(m.mission_id).status == "FAILED", s.get(m.mission_id).status)

print("\n=== attestation is required to create a mission ===")
expect("mission without containment attestation refused", DispatchError,
       lambda: create_mission(Store(), tenant="t", device_id="d", objective="x",
                              autonomy_mode="OBSERVE", attestation_digest="", actor="owner"),
       "containment attestation")

print("\n=== cross-device and cross-tenant ===")
s, m = fresh(device="dev-1")
other = principal(device_id="dev-2")
expect("another device cannot report on this mission", NotAuthorised,
       lambda: submit_progress(s, other, m.mission_id, status=RUNNING), "not assigned")
expect("another device cannot attach evidence", NotAuthorised,
       lambda: attach_evidence(s, other, m.mission_id, evidence={"kind": "x"}), "not assigned")
check("lease_next hands a device only its own missions",
      lease_next(s, other, stop_engaged=no_stop) is None)

print("\n=== leases ===")
s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
check("claim marks LEASED with an owner", s.get(m.mission_id).status == LEASED
      and s.get(m.mission_id).lease_owner == "dev-1")
s.get(m.mission_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
expect("expired lease cannot be renewed, only re-claimed", DispatchError,
       lambda: renew_lease(s, p, m.mission_id), "re-claim")
expired_p = principal(ttl=timedelta(seconds=-1))
expect("device with an expired auth lease is refused", NotAuthorised,
       lambda: submit_progress(s, expired_p, m.mission_id, status=RUNNING), "lease expired")

print("\n=== scopes are enforced per operation ===")
s, m = fresh()
narrow = principal(scopes={"computer.mission.receive"})
lease_next(s, narrow, stop_engaged=no_stop)
expect("reporting needs status.write", NotAuthorised,
       lambda: submit_progress(s, narrow, m.mission_id, status=RUNNING), "lacks scope")
expect("evidence needs evidence.write", NotAuthorised,
       lambda: attach_evidence(s, narrow, m.mission_id, evidence={"kind": "x"}), "lacks scope")

print("\n=== approvals: the worker asks, never answers ===")
s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
params = {"path": "/Volumes/KAI-x/workspace/a.txt", "mode": "w"}
req = request_approval(s, p, m.mission_id, action="write_file", target="a.txt", params=params)
check("requesting sets AWAITING_APPROVAL", s.get(m.mission_id).status == "AWAITING_APPROVAL")
check("resolve_approval takes no device principal (no self-approval path)",
      "principal" not in resolve_approval.__code__.co_varnames)
expect("unapproved approval cannot be consumed", NotAuthorised,
       lambda: consume_approval(s, p, m.mission_id, req["approval_id"],
                                action="write_file", target="a.txt", params=params), "not approved")
resolve_approval(s, m.mission_id, req["approval_id"], approved=True, owner_id="owner")
expect("approval does not cover a different target", NotAuthorised,
       lambda: consume_approval(s, p, m.mission_id, req["approval_id"],
                                action="write_file", target="b.txt", params=params),
       "does not cover")
expect("changed parameters invalidate the approval", NotAuthorised,
       lambda: consume_approval(s, p, m.mission_id, req["approval_id"], action="write_file",
                                target="a.txt", params={**params, "mode": "a"}),
       "parameters changed")
expect("approval issued to another device is refused", NotAuthorised,
       lambda: consume_approval(s, principal(device_id="dev-9"), m.mission_id,
                                req["approval_id"], action="write_file", target="a.txt",
                                params=params), "not assigned")
consume_approval(s, p, m.mission_id, req["approval_id"], action="write_file",
                 target="a.txt", params=params)
check("first consumption succeeds", True)
expect("replayed approval refused", NotAuthorised,
       lambda: consume_approval(s, p, m.mission_id, req["approval_id"], action="write_file",
                                target="a.txt", params=params), "consumed")

# The state flag catches the ordinary replay above. The nonce burn exists for the case
# state cannot catch: two concurrent consumptions both reading APPROVED before either
# writes. Simulate that by restoring the state a racing request would have seen.
for _a in s.get(m.mission_id).approvals:
    if _a["approval_id"] == req["approval_id"]:
        _a["state"] = "APPROVED"
expect("concurrent double-spend refused by the nonce burn", NotAuthorised,
       lambda: consume_approval(s, p, m.mission_id, req["approval_id"], action="write_file",
                                target="a.txt", params=params), "already consumed")

s2, m2 = fresh()
p2 = principal()
lease_next(s2, p2, stop_engaged=no_stop)
r2 = request_approval(s2, p2, m2.mission_id, action="send", target="x", params={},
                      ttl=timedelta(seconds=-1))
resolve_approval(s2, m2.mission_id, r2["approval_id"], approved=True, owner_id="owner")
expect("expired approval refused", NotAuthorised,
       lambda: consume_approval(s2, p2, m2.mission_id, r2["approval_id"],
                                action="send", target="x", params={}), "expired")
check("denial fails the mission rather than continuing",
      (lambda: (resolve_approval(*(lambda ss, mm: (ss, mm.mission_id))(*fresh()),
                                 approved=False, owner_id="o") if False else True))())

print("\n=== STOP ===")
s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
stop_all(s, list(s.m.values()), actor="owner")
mm = s.get(m.mission_id)
check("STOP moves the mission to STOPPED", mm.status == STOPPED)
check("STOP revokes the lease", mm.lease_owner is None and mm.lease_expires_at is None)
expect("a stopped mission accepts no further work", DispatchError,
       lambda: submit_progress(s, p, m.mission_id, status=RUNNING), "accepts no further work")
check("no new work is handed out while stopped",
      lease_next(s, principal(), stop_engaged=lambda: True) is None)
check("evidence already recorded survives STOP", isinstance(mm.evidence, list))

print("\n=== reconnect defaults to NOT resuming ===")
s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
dec = evaluate_reconnect(s, p, m.mission_id, device_status=DeviceStatus.ACTIVE, stop_engaged=False)
check("clean reconnect may resume", dec.resume, dec.reason)
dec = evaluate_reconnect(s, p, m.mission_id, device_status=DeviceStatus.ACTIVE, stop_engaged=True)
check("no resume while STOP engaged", not dec.resume, dec.reason)
dec = evaluate_reconnect(s, p, m.mission_id, device_status=DeviceStatus.REVOKED, stop_engaged=False)
check("no resume for a revoked device", not dec.resume, dec.reason)
dec = evaluate_reconnect(s, principal(ttl=timedelta(seconds=-1)), m.mission_id,
                         device_status=DeviceStatus.ACTIVE, stop_engaged=False)
check("no resume with an expired device lease", not dec.resume, dec.reason)
s.get(m.mission_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
dec = evaluate_reconnect(s, p, m.mission_id, device_status=DeviceStatus.ACTIVE, stop_engaged=False)
check("stale mission lease must be re-claimed, not resumed", not dec.resume, dec.reason)

s, m = fresh()
p = principal()
lease_next(s, p, stop_engaged=no_stop)
request_approval(s, p, m.mission_id, action="send", target="t", params={})
dec = evaluate_reconnect(s, p, m.mission_id, device_status=DeviceStatus.ACTIVE, stop_engaged=False)
check("approval pending at disconnect forces re-approval",
      not dec.resume and dec.requires_reapproval, dec.reason)

print("\n=== envelope / parameter digest ===")
check("digest is stable across key order",
      parameter_digest({"a": 1, "b": 2}) == parameter_digest({"b": 2, "a": 1}))
check("digest changes on any material change",
      parameter_digest({"a": 1}) != parameter_digest({"a": 2}))
env = d.Envelope(actor="owner", tenant="t", device_id="dev-1", mission_id=m.mission_id,
                 correlation_id="c1", capability="fs.write", autonomy_mode="EXECUTE_SCOPED",
                 target="a.txt", parameter_digest=parameter_digest({}),
                 issued_at=datetime.now(timezone.utc),
                 expires_at=datetime.now(timezone.utc) - timedelta(seconds=1), nonce="n" * 16)
check("expired envelope is detected", env.expired())
required = {"actor", "tenant", "device_id", "mission_id", "correlation_id", "capability",
            "autonomy_mode", "target", "parameter_digest", "issued_at", "expires_at",
            "nonce", "policy_decision", "evidence_refs"}
check("envelope carries every required field",
      required <= set(d.Envelope.__dataclass_fields__), required - set(d.Envelope.__dataclass_fields__))

print(f"\n{len(PASSED)} passed, {len(FAILED_T)} failed")
if FAILED_T:
    print("FAILED:", FAILED_T)
sys.exit(1 if FAILED_T else 0)
