"""DETECT_ONLY self-improvement detection (continuous, read-only, PREPARATION authority OFF).

Mirrors the holding watch loop (watch.py): sense evidence-backed improvement candidates from READ-ONLY
certified signals, dedup by a stable root signature, confirm via the certified suite, rank, diff against
the last-seen set, and notify the owner ONLY on a materially-new confirmed candidate (spam-free — one
alert when it appears, not every cycle). It NEVER dispatches A2, creates a worktree, or invokes a coding
agent: this module imports NO write path. Detection authority (KAI_SELF_IMPROVEMENT_DETECT_ENABLED) is
strictly separate from preparation authority (KAI_SELF_IMPROVEMENT_ENABLED). Report-only; mutates only its
own detection-state row. Pure/injectable (run_suite_fn + now + store passed in) so the whole thing is a
plain python3 self-test.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

# §6 eligible detection categories; §7 excluded surfaces are OWNER_REVIEW_REQUIRED, never a write candidate.
ELIGIBLE_CATEGORIES = frozenset({
    "CORRECTNESS_REGRESSION", "FAILING_CERTIFIED_TEST", "DOCUMENTATION_ACCURACY",
    "BOUNDED_MAINTAINABILITY", "REPEATED_CAPABILITY_FAILURE", "OBSERVABILITY_DEFECT",
    "MEASURABLE_OPERATOR_EFFICIENCY"})
EXCLUDED_SURFACES = frozenset({
    "authentication", "authorization", "owner_boundary", "action_class", "approval_policy", "a2_policy",
    "financial", "money_mode", "credentials", "secret_management", "deployment_policy", "security_tier",
    "restricted_security", "dependency_upgrade", "architecture_rewrite", "database_privilege"})

# Certified READ-ONLY suites detection runs each cycle to sense correctness signals (non-authority only).
DETECTION_SUITES = ("holding_self_model", "holding_reconciler", "si_before_after")
DAILY_CONFIRMED_CEILING = 3          # §5 surfacing cap; zero is always valid (§4 no-change rule)
_SEV = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
_CAT_WEIGHT = {"FAILING_CERTIFIED_TEST": 5, "CORRECTNESS_REGRESSION": 5, "REPEATED_CAPABILITY_FAILURE": 4,
               "OBSERVABILITY_DEFECT": 3, "BOUNDED_MAINTAINABILITY": 2, "DOCUMENTATION_ACCURACY": 1,
               "MEASURABLE_OPERATOR_EFFICIENCY": 2}


@dataclass
class Candidate:
    signature: str                    # stable dedup key — one per root problem (§11)
    category: str
    subsystem: str
    problem: str
    evidence: dict = field(default_factory=dict)
    confirmed: bool = False           # a certified test actually reproduced the defect (§8/§9)
    severity: str = "MEDIUM"
    rank_score: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _rank_score(cat: str, severity: str, confirmed: bool) -> int:
    return _CAT_WEIGHT.get(cat, 1) * 10 + (5 - _SEV.get(severity, 4)) + (100 if confirmed else 0)


def collect_candidates(run_suite_fn, *, suites=DETECTION_SUITES) -> list:
    """READ-ONLY sense: run each certified suite; a genuinely FAILED run is a confirmed candidate. A
    passing suite yields NO candidate. run_suite_fn(suite_id) -> evidence dict (internal_test provider
    shape). Never writes; a suite error is skipped (fail closed → no false candidate)."""
    out = []
    for sid in suites:
        try:
            ev = run_suite_fn(sid) or {}
        except Exception:
            continue                                          # cannot run → no candidate (never fabricate)
        if ev.get("execution") != "COMPLETED":
            continue                                          # infra error is not a defect signal
        if ev.get("test_result") == "FAILED":
            out.append(Candidate(
                signature=f"failing_suite:{sid}", category="FAILING_CERTIFIED_TEST",
                subsystem="holding", problem=f"certified suite '{sid}' has {ev.get('failed')} failing test(s)",
                evidence={"suite_id": sid, "execution": ev.get("execution"), "test_result": ev.get("test_result"),
                          "passed": ev.get("passed"), "failed": ev.get("failed"),
                          "commit_sha": ev.get("commit_sha")},
                confirmed=True, severity="HIGH"))             # a reproduced failing certified test IS the confirmation
    return out


def dedup(cands: list) -> list:
    """§11 one active candidate per root signature (keep the highest-ranked for a signature)."""
    best: dict = {}
    for c in cands:
        c.rank_score = _rank_score(c.category, c.severity, c.confirmed)
        if c.category not in ELIGIBLE_CATEGORIES:             # §7 excluded → not a write candidate
            continue
        if c.signature not in best or c.rank_score > best[c.signature].rank_score:
            best[c.signature] = c
    return sorted(best.values(), key=lambda c: -c.rank_score)


def detect(run_suite_fn, *, suites=DETECTION_SUITES) -> list:
    """Full read-only detection: collect → dedup/rank → confirmed candidates only (§8/§9)."""
    return [c for c in dedup(collect_candidates(run_suite_fn, suites=suites)) if c.confirmed]


def _format_alert(new_confirmed: list, mode: str) -> str:
    lines = [f"🔎 KAI improvement watch ({mode}) — {len(new_confirmed)} new confirmed candidate(s):"]
    for c in new_confirmed[:10]:
        lines.append(f"[{c.severity}] {c.problem} — evidence: {c.evidence.get('suite_id')} "
                     f"{c.evidence.get('passed')}p/{c.evidence.get('failed')}f. PREPARATION NOT AUTHORIZED.")
    return "\n".join(lines)


def run_detection(*, run_suite_fn=None, store=None, deliver: bool = True, now: str = "",
                  detect_on: bool | None = None, prepare_on: bool | None = None,
                  deliver_fn=None, ceiling: int = DAILY_CONFIRMED_CEILING) -> dict:
    """One detection pass. Flag-gated by KAI_SELF_IMPROVEMENT_DETECT_ENABLED. READ-ONLY: senses candidates,
    diffs vs the last-notified set, notifies the owner ONLY on a materially-new confirmed candidate, and
    persists the snapshot. It PREPARES NOTHING (prepared=0 always) — detection authority never writes. The
    self-model reports 'detected/confirmed', never 'fixing'. Pure/injectable; never raises fatally."""
    try:
        if detect_on is None or prepare_on is None:
            from app.config import settings
            detect_on = bool(getattr(settings, "KAI_SELF_IMPROVEMENT_DETECT_ENABLED", False)) if detect_on is None else detect_on
            prepare_on = bool(getattr(settings, "KAI_SELF_IMPROVEMENT_ENABLED", False)) if prepare_on is None else prepare_on
        if not detect_on:
            return {"ran": False, "reason": "KAI_SELF_IMPROVEMENT_DETECT_ENABLED off", "mode": "OFF"}
        mode = "PREPARE_ALLOWED" if prepare_on else "DETECT_ONLY"
        if run_suite_fn is None:
            from app.services.holding.internal_test import make_internal_test_provider
            prov = make_internal_test_provider()
            run_suite_fn = lambda sid: prov({"suite_id": sid, "company_id": "wheellsverse"})
        if store is None:
            store = DbDetectionStore()
        cands = detect(run_suite_fn)                          # confirmed, deduped, ranked
        st = store.load() or {}
        notified = set(st.get("notified") or [])
        day = (now or "")[:10]
        confirmed_today = int(st.get("confirmed_today") or 0) if st.get("day") == day else 0
        new_confirmed = [c for c in cands if c.signature not in notified]
        # §5 budget: surface at most `ceiling` newly-confirmed candidates/day (zero is valid, §4).
        surfaced = new_confirmed[:max(0, ceiling - confirmed_today)]
        delivered = {"delivered": False, "reason": "no new confirmed candidate" if cands else "NO_ACTION"}
        if deliver and surfaced:
            msg = _format_alert(surfaced, mode)
            if deliver_fn is not None:
                delivered = deliver_fn(msg)
            else:
                try:
                    from app.services.holding.delivery import send_alert
                    delivered = send_alert(msg)
                except Exception as e:
                    delivered = {"delivered": False, "reason": f"delivery error: {str(e)[:60]}"}
        # persist snapshot (report-only; the ONLY thing this loop mutates)
        store.save({"last_run": now, "mode": mode,
                    "candidates": [c.as_dict() for c in cands],
                    "notified": sorted(notified | {c.signature for c in surfaced}),
                    "confirmed_today": confirmed_today + len(surfaced), "day": day})
        verdict = "NO_ACTION" if not cands else "CANDIDATES"
        return {"ran": True, "mode": mode, "verdict": verdict, "prepared": 0,
                "candidates": [c.as_dict() for c in cands], "confirmed_count": len(cands),
                "new_confirmed": [c.signature for c in surfaced], "delivered": delivered}
    except Exception as e:
        return {"ran": False, "reason": f"detect error: {str(e)[:120]}", "mode": "OFF"}


# ── minimal detection-state store (single row JSONB; self-creating; fail-soft) ─────────────────────────
class DbDetectionStore:
    _DDL = "CREATE TABLE IF NOT EXISTS holding_si_detect_state (id INT PRIMARY KEY DEFAULT 1, value JSONB NOT NULL DEFAULT '{}', updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"

    def _db(self):
        from app.database import SessionLocal
        return SessionLocal()

    def load(self) -> dict:
        from sqlalchemy import text
        import json
        try:
            db = self._db()
            try:
                db.execute(text(self._DDL))
                row = db.execute(text("SELECT value FROM holding_si_detect_state WHERE id=1")).fetchone()
                db.commit()
                v = row[0] if row else {}
                return v if isinstance(v, dict) else json.loads(v or "{}")
            finally:
                db.close()
        except Exception:
            return {}

    def save(self, value: dict) -> bool:
        from sqlalchemy import text
        import json
        try:
            db = self._db()
            try:
                db.execute(text(self._DDL))
                db.execute(text("INSERT INTO holding_si_detect_state (id, value, updated_at) VALUES (1, :v, now()) "
                                "ON CONFLICT (id) DO UPDATE SET value=:v, updated_at=now()"),
                           {"v": json.dumps(value)})
                db.commit()
                return True
            finally:
                db.close()
        except Exception:
            return False


class InMemoryDetectionStore:
    def __init__(self): self._v = {}
    def load(self) -> dict: return dict(self._v)
    def save(self, value: dict) -> bool: self._v = dict(value); return True


def demo() -> None:
    """Pure self-check — no DB/network. Proves: NO_ACTION when clean, one candidate when a suite fails,
    dedup, spam-free notification, and that detection PREPARES NOTHING."""
    passing = {"execution": "COMPLETED", "test_result": "PASSED", "passed": 7, "failed": 0, "commit_sha": "x"}
    failing = {"execution": "COMPLETED", "test_result": "FAILED", "passed": 6, "failed": 1, "commit_sha": "x"}
    def clean(sid): return passing
    def one_fail(sid): return failing if sid == "si_before_after" else passing

    # §4 no-change → NO_ACTION, 0 notifications
    st = InMemoryDetectionStore()
    r = run_detection(run_suite_fn=clean, store=st, now="2026-09-03T00:00:00", detect_on=True, prepare_on=False,
                      deliver_fn=lambda m: {"delivered": True})
    assert r["verdict"] == "NO_ACTION" and r["confirmed_count"] == 0 and not r["new_confirmed"], r
    assert r["prepared"] == 0 and r["mode"] == "DETECT_ONLY"

    # a failing suite → exactly one confirmed candidate, notified once
    notes = []
    st2 = InMemoryDetectionStore()
    r2 = run_detection(run_suite_fn=one_fail, store=st2, now="2026-09-03T01:00:00", detect_on=True, prepare_on=False,
                       deliver_fn=lambda m: (notes.append(m) or {"delivered": True}))
    assert r2["verdict"] == "CANDIDATES" and r2["confirmed_count"] == 1, r2
    assert r2["new_confirmed"] == ["failing_suite:si_before_after"], r2
    assert len(notes) == 1 and "PREPARATION NOT AUTHORIZED" in notes[0], notes

    # §11 spam-free: same candidate next cycle → NO new notification
    r3 = run_detection(run_suite_fn=one_fail, store=st2, now="2026-09-03T05:00:00", detect_on=True, prepare_on=False,
                       deliver_fn=lambda m: (notes.append(m) or {"delivered": True}))
    assert r3["confirmed_count"] == 1 and r3["new_confirmed"] == [], r3
    assert len(notes) == 1, "unchanged candidate must NOT re-notify"

    # detect flag OFF → does not run
    assert run_detection(run_suite_fn=one_fail, store=st2, detect_on=False, prepare_on=False)["ran"] is False
    print("self_improvement_detect.demo OK — NO_ACTION clean, 1 candidate on fail, dedup+spam-free, prepared=0")


if __name__ == "__main__":
    demo()
