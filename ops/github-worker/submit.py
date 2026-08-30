"""Host-side seam: KAI submits a policy-gated task to the ISOLATED GitHub read-only worker.

Same strong isolation as the browser worker (read-only rootfs, non-root, all caps dropped,
no-new-privileges, mem/cpu/pids limits, NO host mounts, --rm, --internal network + SOCKS5
egress-allowlist proxy locked to api.github.com). Read-only GitHub GETs only; any write/mutation
is denied before a container starts. A read-only GITHUB_TOKEN may be injected via env at run time
(never baked into the image, never logged); pass it through `token` and it is set as GITHUB_TOKEN
in the worker only.
"""
import json
import os
import subprocess
import time
import uuid

_READ_ONLY = {"get_repo", "list_prs", "get_pr", "list_issues", "ci_status"}
_WRITE = {"create_pr", "merge_pr", "close_pr", "comment", "create_issue", "close_issue",
          "add_label", "create_release", "dispatch_workflow", "edit"}
_PROHIBITED = {"delete_repo", "delete_branch", "force_push", "change_visibility", "rotate_token",
               "add_collaborator", "change_permissions", "delete_release"}

IMAGE = "wv-github-worker:v1"
PROXY_IMAGE = "wv-egress-proxy:v1"
ALLOWED_HOST = "api.github.com"


def _permit(action: str):
    a = (action or "").strip().lower()
    if a in _PROHIBITED:
        return False, f"denied: {a} is prohibited"
    if a in _READ_ONLY:
        return True, "read-only GitHub GET"
    if a in _WRITE:
        return False, "denied: writes require a bound approval (not provided)"
    return False, f"denied: unknown action '{a}' (fail-closed)"


def _iso_flags(name: str) -> list:
    return [
        "--rm", "--name", name,
        "--read-only", "--tmpfs", "/tmp:rw,size=16m,mode=1777",
        "--user", "ghworker",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "256m", "--cpus", "0.5", "--pids-limit", "128",
    ]


def run_github_task(task: dict, *, token: str = "", timeout_s: int = 45) -> dict:
    """Policy-gate then run a read-only GitHub task in an isolated, egress-locked container."""
    ok, reason = _permit(str(task.get("action", "")))
    if not ok:
        return {"status": "denied", "policy": reason}
    sfx = uuid.uuid4().hex[:8]
    name, net, proxy = f"wvgh-{sfx}", f"wvghnet-{sfx}", f"wvghproxy-{sfx}"
    t0 = time.time(); result = {}
    try:
        subprocess.run(["docker", "network", "create", "--internal", net], capture_output=True, check=True)
        subprocess.run(["docker", "run", "-d", "--name", proxy, "--network", net,
                        "-e", "ALLOWED_DOMAINS=" + ALLOWED_HOST, PROXY_IMAGE], capture_output=True, check=True)
        subprocess.run(["docker", "network", "connect", "bridge", proxy], capture_output=True, check=True)
        time.sleep(1.5)
        pip = subprocess.run(["docker", "inspect", "-f",
                              '{{(index .NetworkSettings.Networks "' + net + '").IPAddress}}', proxy],
                             capture_output=True, text=True).stdout.strip() or proxy
        env = ["-e", f"WORKER_PROXY=socks5://{pip}:8888", "-e", "TASK_JSON=" + json.dumps(task)]
        if token:
            env += ["-e", "GITHUB_TOKEN=" + token]   # injected to the worker only; never logged here
        p = subprocess.run(["docker", "run", *_iso_flags(name), "--network", net, *env, IMAGE],
                           capture_output=True, text=True, timeout=timeout_s)
        for line in reversed((p.stdout or "").strip().splitlines()):
            try: result = json.loads(line); break
            except Exception: continue
        if p.returncode != 0 and not result:
            result = {"status": "error", "stderr_tail": (p.stderr or "")[-160:]}
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        result = {"status": "timeout"}
    except subprocess.CalledProcessError as e:
        result = {"status": "error", "setup": str(e.stderr)[-160:]}
    finally:
        subprocess.run(["docker", "kill", proxy], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)
    result["container"] = name
    result["egress"] = f"default-deny via allowlist proxy ({ALLOWED_HOST} only)"
    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result


def cancel(name: str) -> bool:
    return subprocess.run(["docker", "kill", name], capture_output=True).returncode == 0
