"""No-fabrication guard for §60 the GENERALIZED approval evidence package. Run (from backend/):
    python3 -m app.services.holding.test_approval_package

Mirrors test_registry.py: a flat ck() ledger. Proves the ONE builder produces the canonical §60 field
set for ANY approval type (finance / deploy / merge / generic proposal), that self_improvement REUSES it
(not a fork), and that empty fields disclaim honestly rather than fabricating a test/review/rollback.
Pure — no DB.
"""
from app.services.holding.approval_package import build_approval_package, from_proposal, REQUIRED_FIELDS

res = []
def ck(n, ok): res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def run() -> bool:
    # ── canonical §60 field set present for a NON-self-improvement approval (a finance approval) ─────────
    fin = build_approval_package(
        approval_type="finance", objective="Pay the Q3 AWS invoice",
        problem="Invoice due 2026-09-10", evidence=[{"source": "stripe", "ref": "in_123"}],
        proposed_action="Release $4,200 payment to AWS", risk="HIGH_IMPACT",
        environment="production", authority_requested="OWNER approval to move $4,200")
    ck("§60 canonical field set present for a finance approval", REQUIRED_FIELDS <= set(fin))
    ck("finance approval carries the real objective/problem/evidence (not fabricated)",
       fin["objective"] == "Pay the Q3 AWS invoice" and fin["problem"] == "Invoice due 2026-09-10"
       and fin["evidence"] and fin["risk"] == "HIGH_IMPACT")
    ck("a package NEVER carries execute authority (OWNER_REQUIRED / REQUIRE_APPROVAL)",
       fin["authority"] == "OWNER_REQUIRED" and fin["decision"] == "REQUIRE_APPROVAL")

    # ── honesty: no diff/tests/review supplied → disclaims, NEVER fabricates a positive (§0 #16-19) ──────
    ck("no diff supplied → NONE (not a fabricated diff)", fin["diff_artifact"].startswith("NONE"))
    ck("no tests supplied → NOT_APPLICABLE (not a fabricated pass)", fin["tests"].startswith("NOT_APPLICABLE"))
    ck("no review supplied → NOT_PERFORMED (never claims a review that did not happen)",
       fin["independent_review"].startswith("NOT_PERFORMED"))
    empty = build_approval_package(approval_type="deploy", objective="")
    ck("no rollback supplied → REVERSIBLE_UNKNOWN (owner must confirm)",
       empty["rollback"].startswith("REVERSIBLE_UNKNOWN"))
    ck("missing objective disclaims UNSPECIFIED (not blank/guessed)", empty["objective"] == "UNSPECIFIED")

    # ── from_proposal adapts a generic proposals_store row (deploy/merge) to the SAME §60 shape ──────────
    deploy_row = {"id": 7, "title": "Deploy sol backend to production", "severity": "HIGH",
                  "entity": "sol", "source_key": "sol:deploy-drift",
                  "evidence": [{"source": "deployment_status", "ref": "sha:abc123"}],
                  "action": {"proposed_action": "railway up (sol backend)", "risk": "HIGH_IMPACT",
                             "reversible": False, "action_class": "DEPLOY", "diff": "3 files, +40/-2"}}
    dep = from_proposal(deploy_row, approval_type="deploy")
    ck("§60 canonical field set present for a deploy proposal", REQUIRED_FIELDS <= set(dep))
    ck("deploy package maps the row's real fields (title/action/evidence/diff)",
       dep["objective"] == "Deploy sol backend to production"
       and dep["proposed_action"] == "railway up (sol backend)"
       and dep["diff_artifact"] == "3 files, +40/-2" and dep["evidence"])
    ck("non-reversible deploy → rollback disclaims REVERSIBLE_UNKNOWN (not a fabricated 'reversible')",
       dep["rollback"].startswith("REVERSIBLE_UNKNOWN"))
    merge_row = {"id": 8, "title": "Merge fix/x", "action": {"reversible": True, "proposed_action": "merge PR #8"}}
    mg = from_proposal(merge_row, approval_type="merge")
    ck("reversible merge → rollback says reversible (reflects the row, not a guess)",
       mg["rollback"].startswith("reversible") and mg["approval_type"] == "merge")

    # ── self_improvement REUSES the shared builder (not a fork): its package carries the §60 field set ──
    from app.services.holding.self_improvement import SelfImprovementEngine

    class _Cand:
        problem = "reports.build_morning_briefing raises on empty kpi"
        evidence_refs = [{"source": "log", "ref": "trace-1"}]
        diagnosis = "SOURCE_DEFECT"
        desired_outcome = "RELIABILITY"
        test_before_reproduced = True

    class _Prep:
        files_changed = ["app/services/holding/reports.py"]
        branch = "kai/fix-briefing"
        tests_passed = 12
        tests_failed = 0
        evidence = {"diff_summary": "1 file, +3/-1"}

    pkg = SelfImprovementEngine(a2_framework=None).owner_review_package(_Cand(), _Prep())
    ck("self-improvement package carries the canonical §60 field set (shared builder reused)",
       REQUIRED_FIELDS <= set(pkg))
    ck("self-improvement package KEEPS its existing keys (no consumer breakage)",
       pkg.get("tests_before") == "FAIL (reproduced)" and "files_changed" in pkg and "root_cause" in pkg)
    ck("self-improvement approval_type + real independent review recorded",
       pkg["approval_type"] == "self_improvement" and "certified" in pkg["independent_review"])

    n = len(res); ok = sum(res)
    print(f"\nAPPROVAL PACKAGE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
