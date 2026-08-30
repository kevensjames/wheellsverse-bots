"""GitHub read-only worker task-runner (runs INSIDE an isolated container).

Deterministic read-only GitHub REST GETs only — NO writes, ever. Reads one structured task from
TASK_JSON, enforces a read-only action allowlist itself (defense in depth), routes ALL traffic
through the SOCKS5 egress-allowlist proxy (the internal network has no direct egress; the proxy
permits only api.github.com), and prints a structured JSON summary. The GITHUB_TOKEN (if provided)
is used ONLY in the Authorization header and is NEVER printed — every output path scrubs it.
"""
import json
import os
import sys
import urllib.request

READ_ONLY = {"get_repo", "list_prs", "get_pr", "list_issues", "ci_status"}
_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def _scrub(s: str) -> str:
    return s.replace(_TOKEN, "***") if _TOKEN else s


def _fail(msg, **extra):
    print(json.dumps({"status": "denied", "error": _scrub(msg), **extra})); sys.exit(0)


def _summarize(action: str, d) -> dict:
    if action == "get_repo":
        return {"name": d.get("full_name"), "private": d.get("private"),
                "default_branch": d.get("default_branch"), "open_issues": d.get("open_issues_count")}
    if action == "get_pr":
        return {"number": d.get("number"), "title": d.get("title"), "state": d.get("state"),
                "draft": d.get("draft"), "mergeable_state": d.get("mergeable_state")}
    if action in ("list_prs", "list_issues") and isinstance(d, list):
        return {"count": len(d), "items": [{"number": i.get("number"), "title": i.get("title")} for i in d[:20]]}
    if action == "ci_status" and isinstance(d, dict):
        runs = d.get("workflow_runs", [])
        return {"count": len(runs), "runs": [{"name": r.get("name"), "status": r.get("status"),
                "conclusion": r.get("conclusion")} for r in runs[:10]]}
    return {"raw_keys": list(d.keys())[:10] if isinstance(d, dict) else "list"}


def main():
    try:
        task = json.loads(os.environ.get("TASK_JSON", "{}"))
    except Exception:
        _fail("bad TASK_JSON")
    action = str(task.get("action", "")).lower()
    repo = str(task.get("repo", "")).strip()
    if action not in READ_ONLY:
        _fail(f"action '{action}' not permitted by the read-only GitHub worker")
    if not repo or repo.count("/") != 1 or any(c in repo for c in " ?&#\t"):
        _fail("invalid repo (expected 'owner/name')")

    # Route through the SOCKS5 egress-allowlist proxy (remote DNS) — the only way off the internal net.
    proxy = os.environ.get("WORKER_PROXY", "")
    if proxy:
        import socks, socket
        host = proxy.split("://", 1)[-1].rsplit(":", 1)[0]
        port = int(proxy.rsplit(":", 1)[-1])
        socks.set_default_proxy(socks.SOCKS5, host, port, rdns=True)
        socket.socket = socks.socksocket
        # Force REMOTE DNS: urllib calls getaddrinfo() before connecting, which would resolve
        # the target locally (no DNS on the internal net). Return the hostname unresolved so the
        # SOCKS proxy resolves it instead (rdns=True). The proxy IP is still reached directly.
        socket.getaddrinfo = lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (h, p))]

    paths = {
        "get_repo": f"/repos/{repo}",
        "list_prs": f"/repos/{repo}/pulls?state=open&per_page=20",
        "get_pr": f"/repos/{repo}/pulls/{int(task.get('number', 0))}",
        "list_issues": f"/repos/{repo}/issues?state=open&per_page=20",
        "ci_status": f"/repos/{repo}/actions/runs?per_page=10",
    }
    url = "https://api.github.com" + paths[action]
    req = urllib.request.Request(url, headers={
        "User-Agent": "wv-github-worker", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    if _TOKEN:
        req.add_header("Authorization", "Bearer " + _TOKEN)   # NEVER printed
    try:
        with urllib.request.urlopen(req, timeout=int(task.get("maximum_runtime_seconds", 25))) as r:
            data = json.loads(r.read() or b"{}")
            code = r.status
    except urllib.error.HTTPError as e:
        print(json.dumps({"status": "http_error", "code": e.code, "action": action, "repo": repo}))
        sys.exit(0)
    except Exception as e:
        print(json.dumps({"status": "error", "error": _scrub(str(e))[:200]})); sys.exit(0)
    print(json.dumps({"status": "completed", "action": action, "repo": repo, "http": code, **_summarize(action, data)}))


if __name__ == "__main__":
    main()
