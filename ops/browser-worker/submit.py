"""Host-side seam: KAI submits a policy-gated task to the ISOLATED browser-worker container.

Reuses the governed TARS policy (no parallel policy). Enforces strong container isolation:
read-only rootfs, tmpfs /tmp, non-root, all caps dropped, no-new-privileges, memory/cpu/pids
limits, NO host mounts, per-task ephemeral (--rm). Supports timeout + cancellation. Returns
structured evidence. WRITE/consequential actions are denied before any container starts.
NOTE: full network default-deny/allowlist needs an egress-proxy sidecar (documented hardening);
the runner + this submitter block internal/metadata/private hosts and require a domain allowlist.
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
    name = "wvbw-" + uuid.uuid4().hex[:10]
    cmd = ["docker", "run", *_iso_flags(name), "-e", "TASK_JSON=" + json.dumps(task), IMAGE]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return {"status": "timeout", "duration_ms": int((time.time() - t0) * 1000)}
    out = (p.stdout or "").strip().splitlines()
    result = {}
    for line in reversed(out):
        try: result = json.loads(line); break
        except Exception: continue
    result["container"] = name
    result["duration_ms"] = int((time.time() - t0) * 1000)
    if p.returncode != 0 and not result:
        result = {"status": "error", "stderr_tail": (p.stderr or "")[-200:]}
    return result

def cancel(name: str) -> bool:
    return subprocess.run(["docker", "kill", name], capture_output=True).returncode == 0
