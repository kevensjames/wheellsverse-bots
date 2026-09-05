"""§89 Multi-agent review panel — no-self-approval guard over the EXTENDED certify_worker_result seam.
Zero-framework — mirrors test_approval_dialog.py. Role reviewers are stubs (NO model runs). Run (from backend/):
    python3 -m app.services.holding.test_review_panel
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import review_panel as rp             # noqa: E402
from app.services.holding.review_panel import convene, ROLES, PANEL_RULES_VERSION   # noqa: E402
from app.services.capability import coding                      # noqa: E402
from app.services.capability.coding import WorkerResult         # noqa: E402

GOOD = [{"source": "repo_inspect:sol/api.py", "freshness": "FRESH"}, {"source": "internal_test:run-7", "timestamp": "t"}]
PLAN = {"plan_id": "p1", "objective": "add rate limit to /api/x", "steps": ["patch", "test"]}


def _role(rid, verdict="APPROVE", evidence=GOOD, findings=()):
    calls = []
    def fn(view, role):
        calls.append((view, role)); return {"verdict": verdict, "findings": list(findings), "evidence": evidence}
    fn.calls = calls
    return (rid, fn)


def _panel(**over):
    p = {"PLANNER": _role("claude-planner"), "DOMAIN_EXPERT": _role("gemini-expert"),
         "SECURITY_REVIEWER": _role("codex-sec"), "INDEPENDENT_VERIFIER": _role("cline-verifier")}
    p.update(over)
    return p


def _calls(panel):
    return sum(len(fn.calls) for _, fn in panel.values())


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    # ── nobody approves their own output (§0 #11 / §89) ───────────────────────────────────────────
    p = _panel(SECURITY_REVIEWER=_role("author-a"))
    try:
        convene(PLAN, author="author-a", panel=p); ok = False
    except ValueError:
        ok = True
    ck("author holding ANY panel role -> ValueError; no reviewer invoked", ok and _calls(p) == 0)
    wr = WorkerResult(task="impl", worker="codex", tests_run=4, tests_passed=4, tests_failed=0)
    p = _panel(INDEPENDENT_VERIFIER=_role("codex"))
    try:
        convene(wr, author="someone-else", panel=p); ok = False        # caller tries to relabel the author
    except ValueError:
        ok = True
    ck("WorkerResult author is result.worker (caller cannot relabel); worker as verifier -> ValueError",
       ok and _calls(p) == 0 and wr.certified is False and wr.reviewed is False)
    p = _panel(INDEPENDENT_VERIFIER=_role("claude-planner"))
    try:
        convene(PLAN, author="a", panel=p); ok = False
    except ValueError:
        ok = True
    ck("INDEPENDENT_VERIFIER sharing an identity with another role -> ValueError", ok and _calls(p) == 0)
    try:
        convene(PLAN, author="", panel=_panel()); ok = False
    except ValueError:
        ok = True
    ck("unknown author -> refused (independence cannot be asserted; fail closed)", ok)
    ck("identity rule IS capability.coding.assert_independent_reviewer; verifier seam IS certify_worker_result",
       rp.assert_independent_reviewer is coding.assert_independent_reviewer
       and rp.certify_worker_result is coding.certify_worker_result)

    # ── completeness ──────────────────────────────────────────────────────────────────────────────
    p = _panel(); del p["SECURITY_REVIEWER"]
    inc = convene(PLAN, author="a", panel=p)
    ck("a missing role -> INCOMPLETE (never a partial approval), nobody invoked",
       inc["outcome"] == "INCOMPLETE" and inc["missing_roles"] == ["SECURITY_REVIEWER"] and _calls(p) == 0)
    ck("ROLES are exactly planner / domain-expert / security-reviewer / independent-verifier",
       ROLES == ("PLANNER", "DOMAIN_EXPERT", "SECURITY_REVIEWER", "INDEPENDENT_VERIFIER"))

    # ── plan review: aggregate rules ──────────────────────────────────────────────────────────────
    p = _panel()
    ap = convene(PLAN, author="a", panel=p)
    ck("all four APPROVE with sourced evidence -> APPROVED, advisory, KAI coordinator decides",
       ap["outcome"] == "APPROVED" and ap["advisory"] is True and "KAI" in ap["final_decision_by"]
       and ap["version"] == PANEL_RULES_VERSION == "1.0.0" and ap["certified"] is None)
    ck("bounded: exactly one call per role (§79); each role sees the plan view + its role",
       _calls(p) == 4 and all(len(fn.calls) == 1 and fn.calls[0][1] == role and fn.calls[0][0]["kind"] == "plan"
                              for role, (_, fn) in p.items()))
    nc = convene(PLAN, author="a", panel=_panel(DOMAIN_EXPERT=_role("gemini-expert", evidence=[])))
    ck("an APPROVE with no sourced evidence is downgraded -> NEEDS_CHANGES (§58 LOW)",
       nc["outcome"] == "NEEDS_CHANGES"
       and next(r for r in nc["reviews"] if r["role"] == "DOMAIN_EXPERT")["verdict"] == "NEEDS_CHANGES")
    rj = convene(PLAN, author="a", panel=_panel(SECURITY_REVIEWER=_role("codex-sec", "REJECT", findings=["secret in diff"])))
    ck("any REJECT -> REJECTED with the finding carried",
       rj["outcome"] == "REJECTED" and "secret in diff" in next(r for r in rj["reviews"] if r["role"] == "SECURITY_REVIEWER")["findings"])
    ck("a malformed verdict -> REJECT (fail closed)",
       convene(PLAN, author="a", panel=_panel(PLANNER=_role("claude-planner", "LGTM")))["outcome"] == "REJECTED")

    # ── worker-result review: the verifier IS the certified seam (panel can't be softer) ──────────
    bad = WorkerResult(task="impl", worker="codex", tests_run=3, tests_passed=2, tests_failed=1)
    vb = convene(bad, panel=_panel())
    ck("verifier APPROVE over failing tests -> REJECT via certify_worker_result; result reviewed but NOT certified",
       vb["outcome"] == "REJECTED" and bad.reviewed is True and bad.certified is False and vb["certified"] is False
       and any("certify_worker_result refused" in f
               for f in next(r for r in vb["reviews"] if r["role"] == "INDEPENDENT_VERIFIER")["flags"]))
    none_ran = WorkerResult(task="impl", worker="codex", tests_run=0)
    ck("'done' with no tests run -> never certified, panel REJECTED",
       convene(none_ran, panel=_panel())["outcome"] == "REJECTED" and none_ran.certified is False)
    good = WorkerResult(task="impl", worker="codex", tests_run=4, tests_passed=4, tests_failed=0)
    vg = convene(good, panel=_panel())
    ck("passing tests + four sourced APPROVEs -> APPROVED and the seam certified the result (reviewed_by = verifier)",
       vg["outcome"] == "APPROVED" and good.certified is True and good.reviewed is True and vg["certified"] is True
       and vg["author"] == "codex" and vg["panel"]["INDEPENDENT_VERIFIER"] == "cline-verifier")
    ck("tests_ok=False from the caller overrides -> not certified, REJECTED",
       convene(WorkerResult(task="i", worker="codex", tests_run=2, tests_passed=2), panel=_panel(),
               tests_ok=False)["outcome"] == "REJECTED")
    ck("deterministic: same subject + same replies -> identical report",
       convene(PLAN, author="a", panel=_panel()) == convene(PLAN, author="a", panel=_panel()))
    src = Path(rp.__file__).read_text()
    ck("panel executes/merges/deploys nothing (no subprocess/http/brain import)",
       all(t not in src for t in ("import subprocess", "import requests", "httpx", "capability.brain", "nai_brain")))

    n = len(res); ok = sum(res)
    print(f"\nREVIEW PANEL (§89) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
