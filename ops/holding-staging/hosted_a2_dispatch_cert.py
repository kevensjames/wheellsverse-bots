"""LIMITED_A2 hosted-DISPATCH certification (local, real git, deterministic worker).

Certifies the governor↔worker split that closes LIMITED_A2_HOSTED, minus the live host:
deployed KAI ENQUEUES a governed A2 coding job (staging + 3 brakes + grant + base_sha) -> the worker leaf
runs the WHOLE prepare() with real git (worktree -> bounded fix -> authoritative diff -> shared gates ->
independent test -> independent review) -> deployed KAI VERIFIES the returned evidence and sets the
authoritative decision. Adversarial: brake matrix, cross-company, forged evidence (merged/deploy, company/
base swap, authority/dependency diff), never-release. DB-free (injected enqueue). The real hosted proof
adds only: a live colima runner claiming over HTTP + a real coding CLI.

    python3 ops/holding-staging/hosted_a2_dispatch_cert.py
"""
import importlib.util
import os
import subprocess
import sys
from types import SimpleNamespace

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))

from app.services.holding.a2_dispatch import enqueue_a2_coding_job, verify_a2_evidence  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


coding = _load(os.path.join(REPO, "ops/coding-worker/submit.py"), "coding_submit")
HEAD = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def _settings(app_env="staging", b1=True, b2=True, b3=True):
    return SimpleNamespace(APP_ENV=app_env, KAI_CAPABILITY_EXECUTION_ENABLED=b1,
                           HOLDING_AUTONOMY_ENABLED=b2, KAI_A2_EXECUTION_ENABLED=b3)


def _capture_enqueue():
    box = {"calls": []}
    def enq(proposal_id, worker, task, *, idempotency_key, mission_id):
        box["calls"].append({"worker": worker, "task": task, "idem": idempotency_key})
        return {"id": len(box["calls"]), "correlation_id": "corr", "deduped": False}
    return box, enq


print("LIMITED-A2 HOSTED-DISPATCH CERT (local, real git, deterministic worker)")
print(f"  repo={REPO}  base_sha={HEAD[:12]}")

print("STEP 1 — DISPATCH GATE: deployed KAI enqueues a governed coding job (only routing fields travel)")
box, enq = _capture_enqueue()
r = enqueue_a2_coding_job(mission_id="m1", base_sha=HEAD, settings=_settings(), enqueue_fn=enq)
ck("enqueued when staging + 3 brakes + grant + base_sha", r["enqueued"] and r["reason"] == "OK")
ck("job worker='coding' + idempotency_key a2:m1", box["calls"] and box["calls"][0]["worker"] == "coding"
   and box["calls"][0]["idem"] == "a2:m1")
t = box["calls"][0]["task"]
ck("payload carries ONLY non-authoritative routing (no grant/ceilings/denylist/authority)",
   set(t) == {"a2_action_type", "capability", "company_id", "environment", "task_id", "base_sha",
              "base_dir", "suite_id", "repo_slug", "goal"} and "grant" not in t and "max_files" not in str(t))

print("STEP 2 — EXECUTE: the worker runs the WHOLE governed prepare() with real git -> READY_FOR_REVIEW")
ev = coding.run_coding_task(t, repo_dir=REPO)
ck("status completed + state READY_FOR_REVIEW", ev.get("status") == "completed" and ev.get("state") == "READY_FOR_REVIEW")
ck("NEVER merged / deployed", ev.get("merged") is False and ev.get("deployed") is False)
ck("changed set is the REAL git diff (worker self-report ignored)", ev.get("files_changed") == ["ops/a2-cert-fixture/target.py"])
ck("independent test ran + certified + independent reviewer", ev.get("tests_run", 0) > 0
   and ev.get("certified") is True and ev.get("reviewer") == "kai-independent-reviewer")

print("STEP 3 — VERIFY: deployed KAI independently re-verifies the evidence and sets the decision")
d = verify_a2_evidence(ev, expected_company="wheellsverse", expected_base_sha=HEAD)
ck("KAI decision READY_FOR_REVIEW (independently re-verified)", d["decision"] == "READY_FOR_REVIEW", str(d["reasons"]))

print("STEP 4 — BRAKE MATRIX: any gate off -> 0 A2 writes (no job enqueued)")
for label, s, extra in [
        ("APP_ENV != staging", _settings(app_env="production"), {}),
        ("capability brake off", _settings(b1=False), {}),
        ("autonomy brake off", _settings(b2=False), {}),
        ("A2 brake off", _settings(b3=False), {}),
        ("company autonomy off", _settings(), {"company_autonomy": {"wheellsverse": False}}),
        ("no base_sha", _settings(), {"base_sha_override": ""})]:
    b2box, e2 = _capture_enqueue()
    bsha = extra.pop("base_sha_override", HEAD)
    rr = enqueue_a2_coding_job(mission_id="mx", base_sha=bsha, settings=s, enqueue_fn=e2, **extra)
    ck(f"{label} -> refused, 0 jobs", rr["enqueued"] is False and len(b2box["calls"]) == 0, rr["reason"])

print("STEP 5 — GRANT + CROSS-COMPANY: an un-granted company is never dispatched")
b3box, e3 = _capture_enqueue()
rc = enqueue_a2_coding_job(mission_id="mc", base_sha=HEAD, settings=_settings(), company_id="acme-not-granted", enqueue_fn=e3)
ck("un-granted company -> NOT_GRANTED, 0 jobs", rc["enqueued"] is False and rc["reason"] == "NOT_GRANTED" and not b3box["calls"])

print("STEP 6 — ADVERSARIAL VERIFY: forged worker evidence is rejected/owner-gated by deployed KAI")
ck("forged merged=True -> REJECTED", verify_a2_evidence({**ev, "merged": True})["decision"] == "REJECTED")
ck("forged deployed=True -> REJECTED", verify_a2_evidence({**ev, "deployed": True})["decision"] == "REJECTED")
ck("company swap -> REJECTED", verify_a2_evidence({**ev, "company_id": "acme"}, expected_company="wheellsverse")["decision"] == "REJECTED")
ck("base_sha swap -> REJECTED", verify_a2_evidence({**ev, "starting_sha": "deadbeef"}, expected_base_sha=HEAD)["decision"] == "REJECTED")
ck("reported authority diff while claiming READY -> OWNER_REQUIRED",
   verify_a2_evidence({**ev, "files_changed": ["backend/app/config.py"]})["decision"] == "OWNER_REQUIRED")
ck("reported dependency diff while claiming READY -> OWNER_REQUIRED",
   verify_a2_evidence({**ev, "files_changed": ["requirements.txt"]})["decision"] == "OWNER_REQUIRED")
ck("empty reported diff -> not READY (never a clean forge)",
   verify_a2_evidence({**ev, "files_changed": []})["decision"] != "READY_FOR_REVIEW")

print("STEP 7 — IDEMPOTENCY + NEVER-RELEASE")
b4box, e4 = _capture_enqueue()
enqueue_a2_coding_job(mission_id="m1", base_sha=HEAD, settings=_settings(), enqueue_fn=e4)
ck("same mission_id -> same idempotency_key a2:m1 (queue dedups)", b4box["calls"][0]["idem"] == "a2:m1")
ck("a verified READY_FOR_REVIEW still asserts merged/deployed False (owner merges, KAI never does)",
   ev.get("merged") is False and ev.get("deployed") is False and d["decision"] == "READY_FOR_REVIEW")

print("STEP 8 — ADVERSARIAL FIXES: CLI env scrub (A) + malformed diff-lines fail-closed (D)")
os.environ["SESSION_SIGNING_SECRET"] = "supersecret"; os.environ["DATABASE_URL"] = "postgres://x"
scrubbed = coding._scrubbed_env()
ck("CLI env scrub excludes runner secrets (SESSION_SIGNING_SECRET / DATABASE_URL)",
   "SESSION_SIGNING_SECRET" not in scrubbed and "DATABASE_URL" not in scrubbed and "SECRET_KEY" not in scrubbed)
ck("malformed total_diff_lines -> OWNER_REQUIRED (fail closed, no throw)",
   verify_a2_evidence({**ev, "total_diff_lines": "9999x"})["decision"] == "OWNER_REQUIRED")

subprocess.run(["git", "-C", REPO, "worktree", "prune"], capture_output=True, text=True)
n = len(res); ok = sum(res)
print(f"\nLIMITED-A2 HOSTED-DISPATCH CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
