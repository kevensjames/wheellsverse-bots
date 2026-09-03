"""Additional DETECT_ONLY signal sources (§Part A/B) — REPEATED_JOB_FAILURE + CAPABILITY_HEALTH_DEGRADATION.

Read-only, deduped, source-cited, bounded, default-disabled, and importing NO write/worker-dispatch path.
They normalize into the EXISTING detection Candidate model (self_improvement_detect.Candidate) and plug into
the EXISTING run_detection pipeline — no detect_v2, no new engine, no new scheduler. Each only ADDS
evidence-backed candidates; neither can prepare, dispatch, or write. Pure/injectable (job rows + health
snapshots passed in) so the whole thing is a plain python3 self-test.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.holding.self_improvement_detect import Candidate

# ── PART A — REPEATED_JOB_FAILURE ──────────────────────────────────────────────────────────────────────
REPEAT_THRESHOLD = 3          # §3 same-root failures required (versioned, server-owned)
REPEAT_WINDOW_HOURS = 24
_FAILURE_STATUSES = ("failed", "expired")
# §5 tokens that mean a repeated failure is OPERATIONAL, not a KAI code defect — never a self-improvement
# candidate (they retain their correct operational diagnosis).
_NON_DEFECT_TOKENS = (
    "owner_required", "policy", "denied", "not_granted", "brake", "no_material_change", "expected",
    "credential", "unauthorized", "401", "403", "token", "auth_pending", "login",
    "provider", "outage", "unreachable", "503", "429", "rate limit", "rate-limit", "upstream",
    "stale", "deployment_behind", "deployment stale", "worker offline", "worker unavailable",
    "blocked_worker", "not staging", "staging_only")


def _reason_blob(job: dict) -> str:
    ev = job.get("evidence") or {}
    kd = ev.get("kai_decision")
    kd = (kd.get("decision") if isinstance(kd, dict) else kd) or ""
    parts = [job.get("status"), ev.get("state"), kd, ev.get("reason"), ev.get("error")]
    return " ".join(str(p) for p in parts if p).lower()


def _normalize_reason_code(job: dict) -> str:
    """A bounded, stable reason code from authoritative fields — NEVER raw error text as identity (§4)."""
    ev = job.get("evidence") or {}
    blob = _reason_blob(job)
    if job.get("status") == "expired":
        return "RETRY_EXHAUSTED"
    if "timeout" in blob:
        return "TIMEOUT"
    if str(ev.get("status")) == "error" or "error" in blob and "no error" not in blob:
        return "RUNTIME_ERROR"
    if str(ev.get("state")) == "BLOCKED":
        return "GATE_BLOCKED"
    return "CAPABILITY_FAILURE"


def _eligible_failure(job: dict) -> bool:
    if job.get("status") not in _FAILURE_STATUSES:
        return False
    return not any(tok in _reason_blob(job) for tok in _NON_DEFECT_TOKENS)


def _root_signature(job: dict, reason_code: str) -> str:
    """Stable root identity from authoritative fields (company/worker/capability|suite/reason/subsystem).
    Deliberately excludes timestamps/request-IDs/raw text so retries collapse to ONE root (§4)."""
    t = job.get("task") or {}
    cap = t.get("capability") or t.get("suite_id") or job.get("worker") or "?"
    return f"jobfail:{t.get('company_id', '?')}:{job.get('worker', '?')}:{cap}:{reason_code}"


def _within_window(created_at: str, now_iso: str, hours: int) -> bool:
    try:
        c = datetime.fromisoformat(str(created_at).replace("Z", "")[:26])
        n = datetime.fromisoformat(str(now_iso).replace("Z", "")[:26])
        return (n - c) <= timedelta(hours=hours) and c <= n
    except Exception:
        return False


def detect_repeated_job_failures(jobs: list, *, now_iso: str, threshold: int = REPEAT_THRESHOLD,
                                 window_hours: int = REPEAT_WINDOW_HOURS) -> list:
    """Group eligible in-window failures by ROOT signature; a root with >= threshold occurrences is ONE
    confirmed candidate (evidence-cited). One failure is never a candidate. Excluded (operational) failures
    never count. Pure. Returns [Candidate]."""
    groups: dict = {}
    for j in jobs or []:
        if not _eligible_failure(j) or not _within_window(j.get("created_at", ""), now_iso, window_hours):
            continue
        rc = _normalize_reason_code(j)
        groups.setdefault(_root_signature(j, rc), []).append((j, rc))
    out = []
    for root, items in groups.items():
        if len(items) < threshold:
            continue                                          # §3 below threshold → no candidate
        jobs_in = [j for j, _ in items]
        rc = items[0][1]
        t = jobs_in[0].get("task") or {}
        dates = sorted(str(j.get("created_at", ""))[:19] for j in jobs_in)
        out.append(Candidate(
            signature=root, category="REPEATED_CAPABILITY_FAILURE", subsystem="worker/capability",
            problem=f"{len(items)} repeated '{rc}' failures for {t.get('capability') or t.get('suite_id') or jobs_in[0].get('worker')}",
            evidence={"failure_count": len(items), "window_start": dates[0], "window_end": dates[-1],
                      "job_ids": [j.get("id") for j in jobs_in][:20], "normalized_reason": rc,
                      "company": t.get("company_id"), "worker": jobs_in[0].get("worker"),
                      "last_occurrence": dates[-1], "threshold": threshold, "window_hours": window_hours},
            confirmed=True, severity="HIGH", signal_type="REPEATED_JOB_FAILURE", source="NATURAL"))
    return out


# ── PART B — CAPABILITY_HEALTH_DEGRADATION ─────────────────────────────────────────────────────────────
_UNHEALTHY = ("DEGRADED", "FAILED", "OFFLINE", "UNAVAILABLE")
DEGRADE_CLASSES = ("LOCAL_RUNTIME_DEFECT", "CONFIGURATION_BLOCKER", "CREDENTIAL_BLOCKER",
                   "EXTERNAL_PROVIDER_OUTAGE", "UNKNOWN")


def classify_degradation(state: str, reason: str) -> str:
    """§11 — only LOCAL_RUNTIME_DEFECT is an eligible self-improvement candidate; credential/config/external
    are operational blockers, not KAI code defects."""
    r = (reason or "").lower()
    if any(x in r for x in ("credential", "unauthorized", "401", "403", "token", "auth_pending", "login", "no auth")):
        return "CREDENTIAL_BLOCKER"
    if any(x in r for x in ("provider", "outage", "unreachable", "503", "429", "rate limit", "upstream", "external")):
        return "EXTERNAL_PROVIDER_OUTAGE"
    if any(x in r for x in ("config", "misconfig", "not configured", "missing env", "env var", "setting")):
        return "CONFIGURATION_BLOCKER"
    if str(state).upper() in _UNHEALTHY:
        return "LOCAL_RUNTIME_DEFECT"
    return "UNKNOWN"


def detect_capability_degradation(health_now: dict, health_prev: dict, *, now_iso: str) -> tuple:
    """Compare current vs previous capability health. A material unhealthy transition that PERSISTS across 2
    consecutive checks (§10 transient filter) and classifies as LOCAL_RUNTIME_DEFECT becomes ONE candidate;
    credential/config/external persistently-degraded capabilities become operational blockers (NOT self-code
    candidates, §11). Certification state is tracked SEPARATELY from runtime health (§12). Pure. Returns
    (candidates, operational_blockers)."""
    candidates, operational = [], []
    for cap_id, h in (health_now or {}).items():
        state = str((h or {}).get("state") or "UNKNOWN").upper()
        if state not in _UNHEALTHY:
            continue
        prev_state = str(((health_prev or {}).get(cap_id) or {}).get("state") or "").upper()
        if prev_state not in _UNHEALTHY:
            continue                                          # §10 first degraded check → suppress transient
        cls = classify_degradation(state, h.get("reason"))
        certified = bool(h.get("certified"))
        fallback = h.get("fallback_used")
        ev = {"capability_id": cap_id, "previous_state": prev_state, "current_state": state,
              "classification": cls, "certified": certified, "certification_regression": certified,
              "runtime_health": state, "provider": h.get("provider"), "fallback_used": fallback,
              "reason": h.get("reason"), "last_observed": now_iso, "consecutive_degraded_checks": 2}
        if cls == "LOCAL_RUNTIME_DEFECT":
            candidates.append(Candidate(
                signature=f"cap_health:{cap_id}", category="CAPABILITY_HEALTH_DEGRADATION",
                subsystem="capability", problem=f"certified capability '{cap_id}' degraded ({state})" if certified
                else f"capability '{cap_id}' degraded ({state})",
                evidence=ev, confirmed=True, severity=("HIGH" if certified else "MEDIUM"),
                signal_type="CAPABILITY_HEALTH_DEGRADATION", source="NATURAL"))
        else:
            operational.append({"capability_id": cap_id, "classification": cls, "state": state,
                                "reason": h.get("reason"), "certification_regression": certified})
    return candidates, operational


def demo() -> None:
    """Pure self-check — no DB. Covers the §8 + §15 negative cases."""
    N = "2026-09-03T12:00:00"
    def jf(jid, root_cap, reason_state, status="failed", created=N, company="wheellsverse"):
        return {"id": jid, "status": status, "created_at": created, "worker": "coding",
                "task": {"company_id": company, "capability": root_cap},
                "evidence": {"state": reason_state}}

    # §8: 1 failure → 0; 2 → 0; 3 same-root → 1; 3 different-root → 0; owner/policy → 0
    assert detect_repeated_job_failures([jf(1, "c", "BLOCKED")], now_iso=N) == []
    assert detect_repeated_job_failures([jf(1, "c", "BLOCKED"), jf(2, "c", "BLOCKED")], now_iso=N) == []
    three = [jf(1, "c", "BLOCKED"), jf(2, "c", "BLOCKED"), jf(3, "c", "BLOCKED")]
    r = detect_repeated_job_failures(three, now_iso=N)
    assert len(r) == 1 and r[0].evidence["failure_count"] == 3 and r[0].signal_type == "REPEATED_JOB_FAILURE"
    diff = [jf(1, "a", "BLOCKED"), jf(2, "b", "BLOCKED"), jf(3, "c", "BLOCKED")]
    assert detect_repeated_job_failures(diff, now_iso=N) == [], "different roots never combine"
    owner = [jf(i, "c", "OWNER_REQUIRED") for i in range(3)]
    assert detect_repeated_job_failures(owner, now_iso=N) == [], "owner-required is not a defect"
    outside = [jf(i, "c", "BLOCKED", created="2026-09-01T00:00:00") for i in range(3)]
    assert detect_repeated_job_failures(outside, now_iso=N) == [], "out-of-window excluded"

    # §15: healthy→0; single transient→0; persistent internal→1; credential/external→operational not candidate
    assert detect_capability_degradation({"x": {"state": "READY"}}, {}, now_iso=N) == ([], [])
    assert detect_capability_degradation({"x": {"state": "DEGRADED"}}, {"x": {"state": "READY"}}, now_iso=N) == ([], []), "single transient suppressed"
    cands, ops = detect_capability_degradation({"x": {"state": "DEGRADED", "certified": True}},
                                               {"x": {"state": "DEGRADED"}}, now_iso=N)
    assert len(cands) == 1 and cands[0].signal_type == "CAPABILITY_HEALTH_DEGRADATION" and ops == []
    cc, oo = detect_capability_degradation({"y": {"state": "OFFLINE", "reason": "AUTH_PENDING: missing token"}},
                                           {"y": {"state": "OFFLINE"}}, now_iso=N)
    assert cc == [] and oo and oo[0]["classification"] == "CREDENTIAL_BLOCKER", "credential blocker not a self-code candidate"
    ce, oe = detect_capability_degradation({"z": {"state": "FAILED", "reason": "provider 503 outage"}},
                                           {"z": {"state": "FAILED"}}, now_iso=N)
    assert ce == [] and oe and oe[0]["classification"] == "EXTERNAL_PROVIDER_OUTAGE"
    print("self_improvement_signals.demo OK — repeated-job threshold/exclusions + capability transient/classification")


if __name__ == "__main__":
    demo()
