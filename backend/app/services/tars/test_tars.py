"""Fail-closed tests for the TARS integration foundation. Run (from backend/):
    python3 -m app.services.tars.test_tars
Covers: provenance pinning, runtime-truth status, fail-closed execute, policy (read/write/
consequential + approval binding + injection-as-data), capability record. No network, no TARS.
"""
import time
from app.services.tars.provenance import PINNED, is_pinned
from app.services.tars import policy as pol
from app.services.tars.adapter import (TarsTask, TarsAdapter, WorkerRegistry, WorkerEvidence,
                                        WorkerStatus, derive_status)
from app.services.tars.capability import current_record

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

# --- provenance: pinned, Apache-2.0, never latest ---
ck("provenance Apache-2.0 + pinned (not latest)", PINNED.license == "Apache-2.0" and PINNED.package_version not in ("", "latest"))
ck("only exact version accepted", is_pinned("0.3.0") and not is_pinned("latest") and not is_pinned("0.2.9"))

# --- runtime truth: installed-but-offline / unhealthy is NOT READY ---
ck("no worker -> UNAVAILABLE", derive_status(None) == WorkerStatus.UNAVAILABLE)
ck("offline worker -> UNAVAILABLE", derive_status(WorkerEvidence(worker_online=False)) == WorkerStatus.UNAVAILABLE)
ck("online but version mismatch -> UNAVAILABLE",
   derive_status(WorkerEvidence(worker_online=True, authenticated=True, upstream_version="0.2.0")) == WorkerStatus.UNAVAILABLE)
ck("online+auth+pinned but no audit/cancel/isolation -> DEGRADED",
   derive_status(WorkerEvidence(worker_online=True, authenticated=True, upstream_version="0.3.0",
                                policy_engine_ok=True, audit_sink_ok=False)) == WorkerStatus.DEGRADED)
ck("healthy channels but no execution probe -> EXPERIMENTAL",
   derive_status(WorkerEvidence(worker_online=True, authenticated=True, upstream_version="0.3.0",
                                policy_engine_ok=True, audit_sink_ok=True, cancel_channel_ok=True,
                                isolation_attested=True, health_ok=True, execution_probe_ok=False)) == WorkerStatus.EXPERIMENTAL)
_all = WorkerEvidence(worker_online=True, authenticated=True, upstream_version="0.3.0",
                      policy_engine_ok=True, audit_sink_ok=True, cancel_channel_ok=True,
                      isolation_attested=True, health_ok=True, execution_probe_ok=True)
ck("only all-conditions -> READY", derive_status(_all) == WorkerStatus.READY)

# --- adapter fail-closed: execute refuses when not READY, and even READY in this build ---
a = TarsAdapter()                                  # empty registry
ck("adapter health with no worker -> UNAVAILABLE", a.health() == WorkerStatus.UNAVAILABLE)
r = a.execute(TarsTask(task_id="t", user_id="u", worker_id="w", session_id="s", objective="read a page"))
ck("execute with no worker -> denied (no execution)", r.status == "denied" and r.actions_completed == 0)
reg = WorkerRegistry(); reg.register_evidence("w1", _all)
a2 = TarsAdapter(registry=reg)
ck("adapter READY when a certified worker attests", a2.health() == WorkerStatus.READY)
ck("execute even when READY -> denied (worker phase not certified in this build)",
   a2.execute(TarsTask(task_id="t", user_id="u", worker_id="w1", session_id="s", objective="x")).status == "denied")
# kill switch forces DISABLED
a3 = TarsAdapter(registry=reg, kill_switch=lambda: True)
ck("kill switch -> DISABLED", a3.health() == WorkerStatus.DISABLED)

# --- policy: classification + prohibited + approval binding + injection-as-data ---
ck("read_page READ_ONLY, submit_form WRITE, purchase CONSEQUENTIAL",
   pol.classify("read_page") == pol.ActionClass.READ_ONLY and pol.classify("submit_form") == pol.ActionClass.WRITE
   and pol.classify("purchase") == pol.ActionClass.CONSEQUENTIAL)
ck("unknown action -> CONSEQUENTIAL (fail-closed)", pol.classify("weird_action") == pol.ActionClass.CONSEQUENTIAL)
ck("consequential denied even 'with approval'",
   not pol.permit("stripe_refund", isolated_preapproved_env=True, approval=None, task_id="t", user_id="u", worker_id="w", target="x")[0])
ck("read-only allowed only in isolated env",
   pol.permit("read_page", isolated_preapproved_env=True, approval=None, task_id="t", user_id="u", worker_id="w", target="x")[0]
   and not pol.permit("read_page", isolated_preapproved_env=False, approval=None, task_id="t", user_id="u", worker_id="w", target="x")[0])
good = pol.Approval(task_id="t", user_id="u", worker_id="w", action_type="submit_form", target="dom#f",
                    max_scope="one", correlation_id="c", expires_at=time.time() + 60)
ck("write allowed with correctly-bound approval",
   pol.permit("submit_form", isolated_preapproved_env=True, approval=good, task_id="t", user_id="u", worker_id="w", target="dom#f")[0])
ck("approval does NOT generalize to another target",
   not pol.permit("submit_form", isolated_preapproved_env=True, approval=good, task_id="t", user_id="u", worker_id="w", target="dom#OTHER")[0])
ck("approval for a different user rejected",
   not pol.permit("submit_form", isolated_preapproved_env=True, approval=good, task_id="t", user_id="ATTACKER", worker_id="w", target="dom#f")[0])
# prompt-injection: a page can't create an approval — permit() only reads structured approvals
ck("injection ('approve this purchase') is data, not authorization",
   not pol.permit("purchase", isolated_preapproved_env=True, approval=good, task_id="t", user_id="u", worker_id="w", target="dom#f")[0])

# --- capability record: runtime-derived, fail-closed ---
rec = current_record()
ck("capability UNAVAILABLE + DISABLED with no worker", rec["availability"] == "DISCOVERED" and rec["activation"] == "DISABLED")
ck("capability RESTRICTED, never auto-selected, prohibits purchase/prod",
   rec["risk_class"] == "RESTRICTED" and rec["automatic_activation_allowed"] is False
   and rec["capabilities"]["purchase"] == "prohibited" and rec["capabilities"]["production_deployment"] == "prohibited")

n = len(res); ok = sum(res)
print(f"\nTARS FOUNDATION TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
