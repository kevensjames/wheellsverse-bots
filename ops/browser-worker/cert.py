"""Milestone certification for the isolated deterministic browser worker.
Requires the image wv-browser-worker:v1.47.0 (build first) + colima/docker running.
Proves: approved read-only task executes with isolation + evidence; write/prohibited denied
(host policy); runner defense-in-depth denial; cancellation kills a running container.
"""
import json, subprocess, sys, threading, time, uuid, os
sys.path.insert(0, os.path.dirname(__file__))
import submit

res = []
def ck(n, ok, d=""): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))

# 1) approved READ-ONLY task → executes in an isolated container, returns evidence
t = {"task_id": "cert1", "user_id": "owner", "action": "read_page",
     "url": "https://app.wheellsverse.com", "allowed_domains": ["app.wheellsverse.com"],
     "maximum_runtime_seconds": 40}
r = submit.run_browser_task(t, isolated_preapproved_env=True, timeout_s=90)
ck("read-only task executes in isolated container", r.get("status") == "completed", json.dumps(r)[:160])
ck("evidence returned (title + final_url)", bool(r.get("title")) and bool(r.get("final_url")),
   f"title={r.get('title')!r}")

# 2) WRITE action denied by host policy BEFORE any container starts
w = submit.run_browser_task({"task_id": "cert2", "user_id": "owner", "action": "submit_form",
                             "url": "https://app.wheellsverse.com", "allowed_domains": ["app.wheellsverse.com"]})
ck("WRITE (submit_form) denied by policy (no container)", w.get("status") == "denied", w.get("policy", ""))

# 3) prohibited action denied
pr = submit.run_browser_task({"task_id": "cert3", "user_id": "owner", "action": "purchase",
                              "url": "https://app.wheellsverse.com", "allowed_domains": ["app.wheellsverse.com"]})
ck("prohibited (purchase) denied by policy", pr.get("status") == "denied")

# 4) runner defense-in-depth: bypass host policy, run a write action directly in the container → runner refuses
name = "wvbw-dind-" + uuid.uuid4().hex[:8]
bad_task = json.dumps({"action": "submit_form", "url": "https://app.wheellsverse.com", "allowed_domains": ["app.wheellsverse.com"]})
p = subprocess.run(["docker", "run", *submit._iso_flags(name), "-e", "TASK_JSON=" + bad_task, submit.IMAGE],
                   capture_output=True, text=True, timeout=60)
dind = {}
for line in reversed((p.stdout or "").strip().splitlines()):
    try: dind = json.loads(line); break
    except Exception: continue
ck("runner refuses a write action even if host policy is bypassed", dind.get("status") == "denied", dind.get("error", ""))

# 5) cancellation: start a long-running worker container, kill it mid-flight, confirm it stops
cname = "wvbw-cancel-" + uuid.uuid4().hex[:8]
proc = subprocess.Popen(["docker", "run", "--rm", "--name", cname, *submit._iso_flags(cname)[3:], submit.IMAGE, "sleep", "25"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)
running_before = subprocess.run(["docker", "ps", "-q", "-f", f"name={cname}"], capture_output=True, text=True).stdout.strip()
killed = submit.cancel(cname)
try: proc.wait(timeout=20)
except Exception: pass
still = subprocess.run(["docker", "ps", "-q", "-f", f"name={cname}"], capture_output=True, text=True).stdout.strip()
ck("cancellation kills a running worker container", bool(running_before) and killed and not still,
   f"running_before={bool(running_before)} killed={killed} still_running={bool(still)}")

n = len(res); ok = sum(res)
print(f"\nBROWSER-WORKER MILESTONE: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
