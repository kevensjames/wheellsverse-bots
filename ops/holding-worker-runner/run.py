"""Holding worker-runner — persistent, on the operator's colima host (where Docker is available).

Prod (kai-prod) never runs Docker; it only QUEUES approved worker jobs. This runner claims them over
owner-authed HTTP, runs the CERTIFIED read-only worker in its isolated container, HEARTBEATS to hold
its lease, and posts evidence back. Isolation preserved: only this host executes containers, and only
jobs a human already approved (the executor enqueues only from approved proposals).

Persistence: run under launchd (KeepAlive) — see com.wheellsverse.kai-holding-worker.plist + install.sh.
Reliability: stable worker_id, lease heartbeat, bounded exponential backoff + jitter on API failure,
graceful stop on SIGTERM/SIGINT, and typed allowlisted tasks (the workers refuse writes / unknown actions).

Secret handling: SESSION_SIGNING_SECRET is read from the macOS Keychain (never plaintext on disk); it is
used only to mint an owner cookie and is never logged. Set once via install.sh. `railway run` (which
injects the env) also works for a manual run.

Env: BASE_URL (required), POLL_SECONDS (default 20), LEASE_SECONDS (default 300), WORKER_RUNNER_ONESHOT
(set to run one sweep and exit, e.g. for `railway run`).
"""
import importlib.util
import json
import os
import random
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)                                   # core.operator_session
BASE = os.environ.get("BASE_URL", "").rstrip("/")
POLL = int(os.environ.get("POLL_SECONDS", "20"))
LEASE = int(os.environ.get("LEASE_SECONDS", "300"))
ONESHOT = bool(os.environ.get("WORKER_RUNNER_ONESHOT"))
VERSION = "1.0.0"
HOST_ID = socket.gethostname().split(".")[0]
WORKER_ID = os.environ.get("WORKER_ID") or f"holding-worker-{HOST_ID}-01"
_STOP = threading.Event()


def _secret() -> str:
    s = os.environ.get("SESSION_SIGNING_SECRET", "")
    if s:
        return s
    try:  # macOS Keychain — never stored plaintext on disk
        out = subprocess.run(["security", "find-generic-password", "-s", "kai-holding-worker",
                              "-a", "SESSION_SIGNING_SECRET", "-w"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""


SECRET = _secret()


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _post(path, body=None, *, retries=4):
    """POST with a minted owner cookie + bounded exponential backoff + jitter. Never spins."""
    from core.operator_session import mint_session, ROLE_OWNER
    data = json.dumps(body or {}).encode()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(BASE + path, data=data, method="POST",
                                         headers={"Cookie": "wv_session=" + mint_session(ROLE_OWNER, secret=SECRET),
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 409):     # deterministic — do not retry
                return {"_http_error": e.code}
            if attempt >= retries:
                return {"_http_error": e.code}
        except Exception:
            if attempt >= retries:
                return {"_error": "unreachable"}
        time.sleep(min(30, (2 ** attempt)) + random.random())   # backoff + jitter
    return {"_error": "exhausted"}


def _heartbeat_loop(job_id):
    """Extend the lease every LEASE/3 while a job runs, until stopped."""
    ev = threading.Event()
    def beat():
        while not ev.wait(max(5, LEASE // 3)):
            _post(f"/admin/holding/worker-jobs/{job_id}/heartbeat", {"worker_id": WORKER_ID}, retries=1)
    t = threading.Thread(target=beat, daemon=True); t.start()
    return ev


def process_one(gh, br) -> bool:
    claim = _post("/admin/holding/worker-jobs/claim", {"worker_id": WORKER_ID})
    job = claim.get("job") if isinstance(claim, dict) else None
    if not job:
        return False
    jid, worker, task, corr = job["id"], job["worker"], job["task"], job.get("correlation_id")
    print(f"[{WORKER_ID}] claimed job {jid} corr={corr} · {worker} {task.get('action')} "
          f"{task.get('repo') or task.get('url','')}", flush=True)
    stop_hb = _heartbeat_loop(jid)
    try:
        if worker == "github":
            result = gh.run_github_task(task)
        elif worker == "browser":
            result = br.run_browser_task(task)
        else:
            result = {"status": "denied", "reason": f"unknown worker {worker}"}
        status = "succeeded" if result.get("status") == "completed" else "failed"
    except Exception as e:
        result, status = {"status": "error", "error": str(e)[:200]}, "failed"
    finally:
        stop_hb.set()
    result["worker_id"] = WORKER_ID
    _post(f"/admin/holding/worker-jobs/{jid}/complete", {"evidence": result, "status": status, "worker_id": WORKER_ID})
    print(f"[{WORKER_ID}]  -> {status}: {json.dumps(result)[:140]}", flush=True)
    return True


def main() -> int:
    if not BASE or not SECRET:
        print("FATAL: set BASE_URL and provide SESSION_SIGNING_SECRET (Keychain or `railway run`).")
        return 2
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: _STOP.set())
    gh = _load("ops/github-worker/submit.py", "gh_submit")
    br = _load("ops/browser-worker/submit.py", "br_submit")
    print(f"[{WORKER_ID}] runner up · v{VERSION} · host={HOST_ID} · base={BASE} · oneshot={ONESHOT}", flush=True)
    processed = 0
    while not _STOP.is_set():
        did = process_one(gh, br)
        if did:
            processed += 1
            continue                                # drain the queue back-to-back
        if ONESHOT:
            break
        _STOP.wait(POLL)                            # idle: poll cadence, interruptible
    print(f"[{WORKER_ID}] stopping · processed {processed} job(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
