"""Host-side seam: KAI submits a policy-gated task to the ISOLATED browser-worker container.

Reuses the governed TARS policy (no parallel policy). Enforces strong container isolation:
read-only rootfs, tmpfs /tmp, non-root, all caps dropped, no-new-privileges, memory/cpu/pids
limits, NO host mounts, per-task ephemeral (--rm). Supports timeout + cancellation. Returns
structured evidence. WRITE/consequential actions are denied before any container starts.
Network egress is DEFAULT-DENY: the worker runs on an --internal network (no direct internet)
and all traffic is forced through an egress-allowlist SOCKS5 proxy sidecar (see proxy/), so a
compromised runner cannot reach a non-allowlisted host — enforced at the network layer.
"""
import json, os, subprocess, sys, time, uuid

# Self-contained policy mirroring backend/app/services/tars/policy.py (unified in the full
# integration). READ_ONLY runs in the pre-approved isolated env; WRITE needs a bound approval;
# anything else / prohibited is denied (fail-closed).
_READ_ONLY = {"open_url", "read_page", "screenshot", "navigate", "search", "extract_text"}
_WRITE = {"type_text", "fill_form", "submit_form", "upload_file", "download_file", "send_message"}
_PROHIBITED = {"purchase", "payment", "stripe_refund", "production_deploy", "expose_secret",
               "delete_data", "change_password", "shell_execution", "credential_entry"}

def _permit(action: str, *, isolated_preapproved_env: bool):
    a = (action or "").strip().lower()
    if a in _PROHIBITED:
        return False, f"denied: {a} is prohibited"
    if a in _READ_ONLY:
        return (True, "read-only in isolated env") if isolated_preapproved_env else (False, "read-only needs isolated env")
    if a in _WRITE:
        return False, "denied: WRITE requires a bound approval (not provided)"
    return False, f"denied: unknown action '{a}' (fail-closed)"

IMAGE = "wv-browser-worker:v1.47.0"
PROXY_IMAGE = "wv-egress-proxy:v1"

def _iso_flags(name: str) -> list:
    return [
        "--rm", "--name", name,
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--user", "pwuser",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
        # no -v host mounts; no --privileged; no docker socket
    ]

def run_browser_task(task: dict, *, isolated_preapproved_env: bool = True, timeout_s: int = 60) -> dict:
    """Policy-gate then run the task in an isolated container. Read-only only here."""
    action = str(task.get("action", "")).lower()
    ok, reason = _permit(action, isolated_preapproved_env=isolated_preapproved_env)
    if not ok:
        return {"status": "denied", "policy": reason}
    sfx = uuid.uuid4().hex[:8]
    name, net, proxy = f"wvbw-{sfx}", f"wvbwnet-{sfx}", f"wvbwproxy-{sfx}"
    allow = ",".join(task.get("allowed_domains", []))
    t0 = time.time(); result = {}
    try:
        # 1) INTERNAL network (no direct internet) for the worker
        subprocess.run(["docker", "network", "create", "--internal", net], capture_output=True, check=True)
        # 2) egress-allowlist proxy on the internal net + bridge (the only path to the internet)
        subprocess.run(["docker", "run", "-d", "--name", proxy, "--network", net,
                        "-e", "ALLOWED_DOMAINS=" + allow, PROXY_IMAGE], capture_output=True, check=True)
        subprocess.run(["docker", "network", "connect", "bridge", proxy], capture_output=True, check=True)
        time.sleep(1.5)   # let the proxy bind
        # proxy IP on the internal net — address it by IP (Chromium resolves the proxy address
        # itself). SOCKS5 does REMOTE DNS: the target hostname is resolved by the proxy, so the
        # worker never needs external DNS (which the internal network doesn't provide).
        pip = subprocess.run(["docker", "inspect", "-f",
                              '{{(index .NetworkSettings.Networks "' + net + '").IPAddress}}', proxy],
                             capture_output=True, text=True).stdout.strip() or proxy
        # 3) worker on the internal net ONLY, all traffic forced through the SOCKS5 proxy
        cmd = ["docker", "run", *_iso_flags(name), "--network", net,
               "-e", f"WORKER_PROXY=socks5://{pip}:8888", "-e", "TASK_JSON=" + json.dumps(task), IMAGE]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        for line in reversed((p.stdout or "").strip().splitlines()):
            try: result = json.loads(line); break
            except Exception: continue
        if p.returncode != 0 and not result:
            result = {"status": "error", "stderr_tail": (p.stderr or "")[-200:]}
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        result = {"status": "timeout"}
    except subprocess.CalledProcessError as e:
        result = {"status": "error", "setup": (e.stderr or b"")[-160:].decode(errors="replace") if isinstance(e.stderr, bytes) else str(e.stderr)[-160:]}
    finally:
        subprocess.run(["docker", "kill", proxy], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)
    result["container"] = name
    result["egress"] = "default-deny via allowlist proxy"
    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result

def cancel(name: str) -> bool:
    return subprocess.run(["docker", "kill", name], capture_output=True).returncode == 0
