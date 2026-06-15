"""Scan: Frontend fetch()/api() calls that have no matching @app.{method} backend route.

The exact technique used in the wheellsverse-bots admin audit — surfaced
84 missing endpoints across 29 domains the first time it ran. Has known
false-positive classes (regex-truncated dynamic URLs) — keep severity
at "low" and let humans triage."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

FETCH_RE = re.compile(
    r"""fetch\(\s*['"`]([^'"`]+)['"`](?:\s*,\s*\{[^}]*method\s*:\s*['"](\w+)['"])?""",
)
API_HELPER_RE = re.compile(
    r"""api\(\s*['"`](/api[^'"`]+)['"`](?:\s*,\s*['"](\w+)['"])?""",
)
ROUTE_RE = re.compile(
    r"""@app\.(get|post|put|delete|patch)\(\s*["']([^"']+)["']""",
)
# APIRouter routes — mounted into the app via app.include_router(...)
ROUTER_DECL_RE = re.compile(
    r"""APIRouter\([^)]*prefix\s*=\s*["']([^"']+)["']""",
)
ROUTER_ROUTE_RE = re.compile(
    r"""@router\.(get|post|put|delete|patch|websocket)\(\s*["']([^"']*)["']""",
)
# Dynamic route registration via app.add_api_route("/path", handler, methods=[...])
ADD_ROUTE_RE = re.compile(
    r"""(?:app|router)\.add_api_route\(\s*["']([^"']+)["'][^)]*methods\s*=\s*\[([^\]]+)\]""",
    re.DOTALL,
)
# `_RAW_PATHS = ["/api/foo", ...]` loops that bulk-register endpoints
BULK_PATH_RE = re.compile(
    r"""for\s+_p\s+in\s+\[([^\]]+)\]:""",
    re.DOTALL,
)


def _normalize(url: str) -> str:
    url = url.split("?")[0]
    url = re.sub(r"\$\{[^}]+\}", "{p}", url)
    return url.rstrip("/")


def _candidate_frontend_files(project: Path) -> list[Path]:
    out = []
    for root in ("dashboard", "frontend", "admin", "src"):
        d = project / root
        if not d.is_dir():
            continue
        for ext in ("*.html", "*.js"):
            for p in d.rglob(ext):
                if any(x in str(p) for x in ("/_archive/", "node_modules")):
                    continue
                out.append(p)
    return out


def _candidate_backend_files(project: Path) -> list[Path]:
    out = []
    for root in ("core", "backend", "app", "src"):
        d = project / root
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if any(x in str(p) for x in ("__pycache__", "/tests/", "_test.py")):
                continue
            out.append(p)
    return out


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    fe: set[tuple[str, str]] = set()
    fe_locations: dict[tuple[str, str], tuple[str, int]] = {}
    for f in _candidate_frontend_files(project):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in FETCH_RE.finditer(content):
            url = m.group(1)
            if not url.startswith("/api"):
                continue
            method = (m.group(2) or "GET").upper()
            key = (method, _normalize(url))
            if key not in fe_locations:
                line = content[:m.start()].count("\n") + 1
                fe_locations[key] = (str(f.relative_to(project)), line)
            fe.add(key)
        for m in API_HELPER_RE.finditer(content):
            url = m.group(1)
            method = (m.group(2) or "GET").upper()
            key = (method, _normalize(url))
            if key not in fe_locations:
                line = content[:m.start()].count("\n") + 1
                fe_locations[key] = (str(f.relative_to(project)), line)
            fe.add(key)

    be: set[tuple[str, str]] = set()
    for f in _candidate_backend_files(project):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # 1. Direct @app.{method}("/path") decorators
        for m in ROUTE_RE.finditer(content):
            be.add((m.group(1).upper(),
                    re.sub(r"\{[^}]+\}", "{p}", m.group(2)).rstrip("/")))

        # 2. APIRouter routes. Each *_router.py declares one router with a
        # prefix and a bunch of @router.{method}("/sub") decorators. Combine
        # them: real path = prefix + sub.
        for prefix_match in ROUTER_DECL_RE.finditer(content):
            prefix = prefix_match.group(1).rstrip("/")
            for rm in ROUTER_ROUTE_RE.finditer(content):
                method = rm.group(1).upper()
                if method == "WEBSOCKET":
                    continue
                sub = rm.group(2)
                full = (prefix + ("/" + sub.lstrip("/") if sub else "")).rstrip("/") or prefix
                be.add((method, re.sub(r"\{[^}]+\}", "{p}", full)))

        # 3. app.add_api_route("/path", handler, methods=[...])
        for m in ADD_ROUTE_RE.finditer(content):
            path = re.sub(r"\{[^}]+\}", "{p}", m.group(1)).rstrip("/")
            for verb in re.findall(r"""['"](\w+)['"]""", m.group(2)):
                be.add((verb.upper(), path))

        # 4. Bulk-path loops like:
        #      for _p in ["/api/sa/status", "/api/sa/store", ...]:
        #          app.get(_p)(handler)
        # Treat each path in the literal list as registered (heuristic: GET).
        for m in BULK_PATH_RE.finditer(content):
            for path_match in re.finditer(r"""['"](/api[^'"]+)['"]""", m.group(1)):
                be.add(("GET", re.sub(r"\{[^}]+\}", "{p}", path_match.group(1)).rstrip("/")))

    if not fe:
        return []
    missing = sorted(fe - be)
    findings: list[dict] = []
    for method, path in missing:
        # Skip non-API resources and likely-dynamic-path artifacts
        if not path.startswith("/api"):
            continue
        loc_file, loc_line = fe_locations.get((method, path), ("(unknown)", 0))
        findings.append({
            "severity": "low",  # high false-positive rate; human triage needed
            "location": f"{loc_file}:{loc_line}",
            "evidence": f"{method} {path}  (called from frontend, no matching @app route)",
            "fix_payload": {"method": method, "path": path},
        })
    return findings[:50]  # cap to avoid drowning the report
