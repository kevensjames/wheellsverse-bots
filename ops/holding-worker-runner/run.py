"""Holding worker-runner — runs on the operator's colima host (where Docker is available).

Prod (kai-prod) never runs Docker; it only QUEUES approved worker jobs. This runner claims those jobs
from App B's queue over owner-authed HTTP, runs the CERTIFIED isolated worker (read-only, in its
isolated container), and posts the evidence back. Isolation is preserved: only this host executes
containers, and only jobs a human already approved (the executor enqueues only from approved proposals).

Run (from repo root, colima up):
  BASE_URL=https://kai-prod-production.up.railway.app \
    railway run --service kai-prod python3 ops/holding-worker-runner/run.py
(`railway run` injects SESSION_SIGNING_SECRET so the runner can mint an owner cookie; it is never printed.)
"""
import importlib.util
import json
import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)                                   # core.operator_session
BASE = os.environ.get("BASE_URL", "").rstrip("/")
SECRET = os.environ.get("SESSION_SIGNING_SECRET", "")
MAX_JOBS = int(os.environ.get("WORKER_RUNNER_MAX_JOBS", "10"))


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _post(path, body=None):
    from core.operator_session import mint_session, ROLE_OWNER
    data = json.dumps(body).encode() if body is not None else b"{}"
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Cookie": "wv_session=" + mint_session(ROLE_OWNER, secret=SECRET),
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read() or b"{}")


def main() -> int:
    if not BASE or not SECRET:
        print("FATAL: set BASE_URL and run under `railway run` (SESSION_SIGNING_SECRET must be injected).")
        return 2
    gh = _load("ops/github-worker/submit.py", "gh_submit")
    br = _load("ops/browser-worker/submit.py", "br_submit")
    ran = 0
    while ran < MAX_JOBS:
        job = (_post("/admin/holding/worker-jobs/claim") or {}).get("job")
        if not job:
            break
        jid, worker, task = job["id"], job["worker"], job["task"]
        print(f"claimed job {jid} · {worker} · {task.get('action')} {task.get('repo') or task.get('url','')}")
        try:
            if worker == "github":
                result = gh.run_github_task(task)
            elif worker == "browser":
                result = br.run_browser_task(task)
            else:
                result = {"status": "denied", "reason": f"unknown worker {worker}"}
            status = "done" if result.get("status") in ("completed",) else "failed"
        except Exception as e:
            result, status = {"status": "error", "error": str(e)[:200]}, "failed"
        _post(f"/admin/holding/worker-jobs/{jid}/complete", {"evidence": result, "status": status})
        print(f"  -> {status}: {json.dumps(result)[:140]}")
        ran += 1
    print(f"worker-runner: processed {ran} job(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
