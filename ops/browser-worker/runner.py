"""Deterministic browser worker task-runner (runs INSIDE an isolated container).

No model, no AI — deterministic Playwright only (Section 1 prefers this over AI browser).
Reads one structured task from the TASK_JSON env var, enforces the read-only allowlist +
domain allowlist itself (defense in depth on top of the host-side policy), runs a fresh
isolated browser context, and prints a structured JSON result to stdout. WRITE/consequential
actions are refused here too — a compromised task cannot make this runner submit a form.
"""
import json, os, sys, time

READ_ONLY = {"open_url", "read_page", "screenshot"}   # this worker does read-only only

def _fail(msg, **extra):
    print(json.dumps({"status": "denied", "error": msg, **extra})); sys.exit(0)

def main():
    try:
        task = json.loads(os.environ.get("TASK_JSON", "{}"))
    except Exception:
        _fail("bad TASK_JSON")
    action = str(task.get("action", "")).lower()
    url = str(task.get("url", ""))
    allowed = [d.lower() for d in task.get("allowed_domains", [])]
    if action not in READ_ONLY:
        _fail(f"action '{action}' not permitted by the deterministic read-only worker")
    if not url.startswith("https://"):
        _fail("only https URLs allowed")
    host = url.split("/", 3)[2].lower() if "://" in url else ""
    # block internal/metadata/private targets outright, and require the allowlist
    bad = ("localhost", "127.", "169.254.", "10.", "192.168.", "0.0.0.0", "metadata")
    if any(host.startswith(b) or b in host for b in bad):
        _fail("blocked internal/metadata/private host")
    if allowed and host not in allowed:
        _fail(f"host '{host}' not in task allowlist")

    from playwright.sync_api import sync_playwright
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context()             # fresh, isolated context per task
        page = ctx.new_page()
        page.set_default_timeout(int(task.get("maximum_runtime_seconds", 30)) * 1000)
        page.goto(url, wait_until="domcontentloaded")
        title = page.title()
        final_url = page.url
        shot = "/tmp/evidence.png"
        try:
            page.screenshot(path=shot)
        except Exception:
            shot = ""
        ctx.close(); browser.close()
    print(json.dumps({
        "status": "completed", "action": action, "title": title, "final_url": final_url,
        "screenshot": shot, "duration_ms": int((time.time() - t0) * 1000),
    }))

if __name__ == "__main__":
    main()
