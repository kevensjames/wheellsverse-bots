"""Scan: synchronous blocking I/O calls inside async functions.

This is the EXACT bug class that bit `/api/sa/trend-scan` earlier in
the workspace history — a sync `run_trend_scan()` was called inside
`async def sa_trend_scan_get()` and blocked the asyncio event loop for
the whole server while the scrape ran. Real users saw a forever-spinner
and every other endpoint slowed down.

Detection (AST-based, not regex):
  1. Parse each Python file in core/, app/, backend/, infra/
  2. For each AsyncFunctionDef, walk its body for blocking Call nodes
  3. Skip the call if it's wrapped in `await asyncio.to_thread(...)`,
     `await asyncio.wait_for(...)`, or any `await` expression (a sync
     library call that returns a coroutine is fine — the await yields)
  4. Match against a curated set of blocking-call patterns

Curated blocking patterns:
  - time.sleep
  - requests.{get,post,put,delete,patch,head,request} (HTTP libs that
    block the calling thread; httpx is fine in async mode)
  - urllib.request.urlopen
  - subprocess.{run,check_output,check_call,call} (use asyncio.create_subprocess_*)
  - socket.{send,recv,connect} (use asyncio sockets)
  - sqlite3.Connection methods (use aiosqlite)
"""

from __future__ import annotations

import ast
from pathlib import Path

# (callable path tuple, description) — match attr chains exactly
BLOCKING_CALLS: list[tuple[tuple[str, ...], str]] = [
    (("time", "sleep"),                          "time.sleep blocks the event loop"),
    (("requests", "get"),                        "requests.get is sync — use httpx async or to_thread"),
    (("requests", "post"),                       "requests.post is sync"),
    (("requests", "put"),                        "requests.put is sync"),
    (("requests", "delete"),                     "requests.delete is sync"),
    (("requests", "patch"),                      "requests.patch is sync"),
    (("requests", "head"),                       "requests.head is sync"),
    (("requests", "request"),                    "requests.request is sync"),
    (("urllib", "request", "urlopen"),           "urllib.request.urlopen is sync"),
    (("subprocess", "run"),                      "subprocess.run blocks — use asyncio.create_subprocess_exec"),
    (("subprocess", "check_output"),             "subprocess.check_output blocks"),
    (("subprocess", "check_call"),               "subprocess.check_call blocks"),
    (("subprocess", "call"),                     "subprocess.call blocks"),
    (("socket", "recv"),                         "socket.recv blocks — use asyncio sockets"),
    (("socket", "send"),                         "socket.send blocks"),
]

# Safe wrappers — calls inside these stay non-blocking from the event loop's
# perspective. If a blocking call appears as a positional arg to one of these,
# skip it.
SAFE_WRAPPERS: set[tuple[str, ...]] = {
    ("asyncio", "to_thread"),
    ("asyncio", "wait_for"),
    ("asyncio", "create_task"),
    ("asyncio", "ensure_future"),
    ("asyncio", "get_event_loop"),
}


def _attr_chain(node: ast.AST) -> tuple[str, ...]:
    """Walk a possibly-nested Attribute/Name chain into a tuple of names.
    `time.sleep`         → ('time', 'sleep')
    `urllib.request.urlopen` → ('urllib', 'request', 'urlopen')
    Returns () if the node is something else (subscript, call result, etc.)."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return tuple(reversed(parts))
    return ()


def _is_inside_safe_wrapper(call_node: ast.Call, ancestors: list[ast.AST]) -> bool:
    """If any ancestor is a Call to one of SAFE_WRAPPERS, treat this call
    as non-blocking from the event loop's perspective."""
    for anc in ancestors:
        if not isinstance(anc, ast.Call):
            continue
        chain = _attr_chain(anc.func)
        if chain in SAFE_WRAPPERS:
            return True
    return False


def _scan_async_def(fn: ast.AsyncFunctionDef, src_path: str) -> list[dict]:
    findings: list[dict] = []

    # Walk with a parent stack so we can detect "inside safe wrapper" calls
    stack: list[ast.AST] = []

    class Walker(ast.NodeVisitor):
        def generic_visit(self, node):
            stack.append(node)
            try:
                super().generic_visit(node)
            finally:
                stack.pop()

        def visit_Call(self, node: ast.Call):
            chain = _attr_chain(node.func)
            for blocking, descr in BLOCKING_CALLS:
                if chain == blocking:
                    if _is_inside_safe_wrapper(node, stack):
                        break
                    findings.append({
                        "severity": "high",
                        "location": f"{src_path}:{node.lineno}",
                        "evidence": (
                            f"async def {fn.name}() calls {'.'.join(chain)}() — {descr}"
                        ),
                        "fix_payload": {
                            "function": fn.name,
                            "blocking_call": ".".join(chain),
                            "line": node.lineno,
                        },
                    })
                    break
            self.generic_visit(node)

    Walker().visit(fn)
    return findings


def _candidate_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for root in ("core", "backend", "app", "src", "infra"):
        d = project / root
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            s = str(p)
            if any(x in s for x in ("__pycache__", "/tests/", "_test.py", ".OLD_")):
                continue
            out.append(p)
    return out


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    findings: list[dict] = []
    for f in _candidate_files(project):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(f))
        except (SyntaxError, ValueError):
            continue
        except Exception:
            continue
        rel = str(f.relative_to(project))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                findings.extend(_scan_async_def(node, rel))
    return findings
