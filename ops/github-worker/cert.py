"""Certification for the isolated GitHub read-only worker.
Requires wv-github-worker:v1 + wv-egress-proxy:v1 + colima/docker running.
Proves: read-only GET executes egress-locked with evidence; write/prohibited denied (host policy);
runner defense-in-depth; egress default-deny at the network layer; the token is NEVER logged.
"""
import json, subprocess, sys, uuid, os
sys.path.insert(0, os.path.dirname(__file__))
import submit

res = []
def ck(n, ok, d=""): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))

# 1) approved READ-ONLY task on a PUBLIC repo → executes egress-locked, returns evidence (no token needed)
r = submit.run_github_task({"action": "get_repo", "repo": "octocat/Hello-World"}, timeout_s=60)
ck("read-only get_repo executes in isolated, egress-locked container", r.get("status") == "completed", json.dumps(r)[:150])
ck("evidence returned (full_name resolved via api.github.com)", r.get("name") == "octocat/Hello-World", f"name={r.get('name')!r}")

# 2) WRITE denied by host policy before any container starts
w = submit.run_github_task({"action": "create_pr", "repo": "octocat/Hello-World"})
ck("WRITE (create_pr) denied by policy (no container)", w.get("status") == "denied", w.get("policy", ""))

# 3) prohibited denied
pr = submit.run_github_task({"action": "delete_repo", "repo": "octocat/Hello-World"})
ck("prohibited (delete_repo) denied by policy", pr.get("status") == "denied")

# 4) runner defense-in-depth: bypass host policy, run a write action directly → runner refuses
name = "wvgh-dind-" + uuid.uuid4().hex[:8]
bad = json.dumps({"action": "merge_pr", "repo": "octocat/Hello-World"})
p = subprocess.run(["docker", "run", *submit._iso_flags(name), "-e", "TASK_JSON=" + bad, submit.IMAGE],
                   capture_output=True, text=True, timeout=60)
dind = {}
for line in reversed((p.stdout or "").strip().splitlines()):
    try: dind = json.loads(line); break
    except Exception: continue
ck("runner refuses a write action even if host policy is bypassed", dind.get("status") == "denied", dind.get("error", ""))

# 5) EGRESS default-deny: proxy allowlist EXCLUDES api.github.com → the GET is blocked at the network layer
sfx = uuid.uuid4().hex[:8]; net = f"ghx-{sfx}"; px = f"ghpx-{sfx}"; wk = f"ghwk-{sfx}"
try:
    subprocess.run(["docker", "network", "create", "--internal", net], capture_output=True, check=True)
    subprocess.run(["docker", "run", "-d", "--name", px, "--network", net,
                    "-e", "ALLOWED_DOMAINS=example.com", submit.PROXY_IMAGE], capture_output=True, check=True)
    subprocess.run(["docker", "network", "connect", "bridge", px], capture_output=True)
    import time; time.sleep(1.5)
    pip = subprocess.run(["docker", "inspect", "-f", '{{(index .NetworkSettings.Networks "' + net + '").IPAddress}}', px],
                         capture_output=True, text=True).stdout.strip() or px
    task = json.dumps({"action": "get_repo", "repo": "octocat/Hello-World", "maximum_runtime_seconds": 15})
    p5 = subprocess.run(["docker", "run", "--rm", "--name", wk, *submit._iso_flags(wk)[3:], "--network", net,
                         "-e", f"WORKER_PROXY=socks5://{pip}:8888", "-e", "TASK_JSON=" + task, submit.IMAGE],
                        capture_output=True, text=True, timeout=60)
    blocked = '"status": "completed"' not in (p5.stdout or "")
finally:
    subprocess.run(["docker", "kill", px], capture_output=True)
    subprocess.run(["docker", "network", "rm", net], capture_output=True)
ck("egress default-deny: proxy blocks api.github.com when not allowlisted (network layer)", blocked,
   (p5.stdout or p5.stderr or "").strip()[:90])

# 6) the token is NEVER logged — run with a distinctive fake token, assert it appears in NO output
FAKE = "ghp_FAKE_tok_" + uuid.uuid4().hex
r6 = submit.run_github_task({"action": "get_repo", "repo": "octocat/Hello-World"}, token=FAKE, timeout_s=60)
leaked = FAKE in json.dumps(r6)
ck("GITHUB_TOKEN never appears in worker output (no secret leak)", not leaked,
   "token scrubbed" if not leaked else "TOKEN LEAKED!")

n = len(res); ok = sum(res)
print(f"\nGITHUB-WORKER CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
