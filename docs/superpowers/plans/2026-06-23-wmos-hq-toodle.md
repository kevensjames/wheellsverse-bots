# W-MOS Portfolio HQ Toodle Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the **Portfolio HQ** admin toodle — a SiteBoost-style FastAPI router + single-file HTML dashboard at `/admin/portfolio` — that makes the dormant W-MOS engine (Plan 1) **visible** (10 businesses, approval queue, audit) and **controllable** (arm/disarm/kill the orchestrator).

**Architecture:** Mirrors the existing SiteBoost toodle convention exactly: a `narai/api/routes/portfolio_admin.py` router (X-API-Key auth via `verify_admin_api_key`), a read-side aggregation module `core/portfolio/rollup.py`, a small extension to `core/portfolio/orchestrator.py` so arm/kill can be persisted (not only env), a single-file `frontend/admin/portfolio.html`, mounted in `core/api.py` with a `%%API_KEY%%`-injecting serve route, and a Command Center card. The HQ reads engine state — it never reaches an adapter, so nothing autonomous can fire from it.

**Tech Stack:** Python 3 / FastAPI, pytest + `fastapi.testclient.TestClient`, vanilla-JS single-file HTML. Stdlib + existing repo deps only.

## Global Constraints

- **Repo / branch:** `wheellsverse-bots` @ `_apexdeploy`. All paths relative to repo root. Builds on Plan-1 engine at HEAD `0b35021`.
- **File header:** every Python module starts with `from __future__ import annotations`.
- **Auth:** every admin endpoint takes `_=Depends(verify_admin_api_key)`. `verify_admin_api_key` is defined locally in the router (mirroring `siteboost_admin.py` / `shopify_admin.py` — the codebase duplicates this dep per router; follow that convention).
- **Router prefix:** `APIRouter(prefix="/api/narai/portfolio", tags=["portfolio-admin"])`.
- **Serve route:** `GET /admin/portfolio` reads `ROOT / "frontend" / "admin" / "portfolio.html"`, injects the admin key by replacing the literal `'%%API_KEY%%'` with the sanitized key (printable ASCII only), returns `HTMLResponse` with `Cache-Control: no-store, no-cache`. Mirror `serve_siteboost_admin` (core/api.py:1665).
- **Mount:** add a `try/except` import + `app.include_router(...)` near core/api.py:15100, mirroring the SiteBoost mount; a broken import must only log a warning, never crash the app.
- **Dormant-by-default preserved:** the orchestrator extension must keep `is_enabled()` False when neither env nor the persisted flag is set; `kill_engaged()` must still be checked first and be True if EITHER env or the persisted flag is set.
- **Engine reuse:** the HQ composes Plan-1 modules (`registry`, `state`, `loops`, `orchestrator`, `paths`) — it does NOT re-implement them and never constructs an adapter.
- **truth_verification skill applies:** tests assert against real persisted state / real HTTP responses, never a bare return code.
- **Run tests from repo root:** `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest <path> -v`.
- **git hygiene:** the tree has UNRELATED dirty files; stage ONLY the files named in each task's commit step — never `git add -A`.
- **Commits:** operator's standing rule is commit-only-when-asked; the per-task commit is the intended boundary, honor approval at execution time.

---

### Task 1: Persisted orchestrator control (arm / disarm / kill from a file)

**Files:**
- Modify: `core/portfolio/orchestrator.py`
- Test: `tests/test_portfolio_orchestrator.py` (append)

**Interfaces:**
- Consumes: `core.portfolio.paths` (`data_root`, `load_json`, `save_json_atomic`).
- Produces (new, in addition to existing `is_enabled`/`kill_engaged`/`run_once`/`start_worker`):
  - `set_enabled(enabled: bool) -> None` — persist `portfolio.json["control"]["enabled"]`.
  - `engage_kill() -> None` / `disengage_kill() -> None` — persist `portfolio.json["control"]["kill"]`.
  - `control_state() -> dict` — `{"enabled": is_enabled(), "kill": kill_engaged()}`.
  - `is_enabled()` / `kill_engaged()` now return True if EITHER the env var OR the persisted flag is set.

- [ ] **Step 1: Write the failing test** (append to `tests/test_portfolio_orchestrator.py`)

```python
def test_persisted_arm_and_kill_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    # dormant + not killed by default
    assert orchestrator.is_enabled() is False
    assert orchestrator.kill_engaged() is False
    # arm via persisted flag
    orchestrator.set_enabled(True)
    assert orchestrator.is_enabled() is True
    assert orchestrator.control_state() == {"enabled": True, "kill": False}
    # kill via persisted flag (checked first in run_once)
    orchestrator.engage_kill()
    assert orchestrator.kill_engaged() is True
    res = orchestrator.run_once(lambda s: None, lambda s: {}, slugs=["n8n"])
    assert res["status"] == "killed"
    # disengage kill, disarm
    orchestrator.disengage_kill()
    orchestrator.set_enabled(False)
    assert orchestrator.kill_engaged() is False
    assert orchestrator.is_enabled() is False


def test_env_still_overrides_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    # env arms even with no persisted flag
    assert orchestrator.is_enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_orchestrator.py::test_persisted_arm_and_kill_flags -v`
Expected: FAIL with `AttributeError: module 'core.portfolio.orchestrator' has no attribute 'set_enabled'`.

- [ ] **Step 3: Write minimal implementation**

In `core/portfolio/orchestrator.py`, add the `paths` import to the existing imports (`from core.portfolio import loops, registry, state` → add `paths`):
```python
from core.portfolio import loops, paths, registry, state
```
Then replace the existing `is_enabled` and `kill_engaged` and add the setters/reader:
```python
def _control() -> dict:
    cfg = paths.load_json(paths.data_root() / "portfolio.json", {})
    return (cfg or {}).get("control", {}) or {}


def is_enabled() -> bool:
    if os.getenv("WMOS_ORCHESTRATOR_ENABLED") == "1":
        return True
    return bool(_control().get("enabled"))


def kill_engaged() -> bool:
    if os.getenv("WMOS_KILL") == "1":
        return True
    return bool(_control().get("kill"))


def _set_control(key: str, value: bool) -> None:
    f = paths.data_root() / "portfolio.json"
    cfg = paths.load_json(f, {}) or {}
    cfg.setdefault("control", {})[key] = bool(value)
    paths.save_json_atomic(f, cfg)


def set_enabled(enabled: bool) -> None:
    _set_control("enabled", enabled)


def engage_kill() -> None:
    _set_control("kill", True)


def disengage_kill() -> None:
    _set_control("kill", False)


def control_state() -> dict:
    return {"enabled": is_enabled(), "kill": kill_engaged()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_orchestrator.py -v`
Expected: PASS (original 5 + 2 new = 7).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/orchestrator.py tests/test_portfolio_orchestrator.py
git commit -m "feat(wmos): persisted orchestrator arm/disarm/kill controls"
```

---

### Task 2: `rollup.py` — HQ read-side aggregation

**Files:**
- Create: `core/portfolio/rollup.py`
- Test: `tests/test_portfolio_rollup.py`

**Interfaces:**
- Consumes: `registry.list_businesses`, `state.load_state`, `loops.load_loop`/`select_next_step`, `paths.read_jsonl`/`data_root`.
- Produces:
  - `business_summary(slug: str, name: str) -> dict` — `{"slug","name","phase","completed","pending","next_step","total_steps"}`.
  - `portfolio_overview() -> list[dict]` — `business_summary` for every registry business, in registry order.
  - `recent_audit(limit: int = 50) -> list[dict]` — last `limit` records from `audit.jsonl`, newest first.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_rollup.py
import json
from core.portfolio import rollup, state, paths


def test_portfolio_overview_covers_all_ten(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    overview = rollup.portfolio_overview()
    assert len(overview) == 10
    n8n = next(b for b in overview if b["slug"] == "n8n")
    assert n8n["name"] == "n8n Automation Agency"
    assert n8n["phase"] == "planning"          # default state
    assert n8n["completed"] == 0
    assert n8n["pending"] == 0
    assert n8n["next_step"] is None            # no loop.json seeded yet
    assert n8n["total_steps"] == 0


def test_business_summary_reflects_state_and_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # seed a loop + some completed/pending state
    d = tmp_path / "n8n"
    d.mkdir(parents=True, exist_ok=True)
    (d / "loop.json").write_text(json.dumps({"business": "n8n", "steps": [
        {"verb": "research_niche", "agent": "kai", "class": "green"},
        {"verb": "draft_outreach", "agent": "kai", "class": "green"},
        {"verb": "run_campaign", "agent": "kai", "class": "auto_capped"},
    ]}))
    state.mark_completed("n8n", "research_niche")
    state.mark_pending("n8n", "draft_outreach")
    s = rollup.business_summary("n8n", "n8n Automation Agency")
    assert s["completed"] == 1
    assert s["pending"] == 1
    assert s["total_steps"] == 3
    assert s["next_step"] == "run_campaign"    # first not completed/pending


def test_recent_audit_newest_first(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.audit({"verb": "a", "status": "executed"})
    state.audit({"verb": "b", "status": "queued"})
    recent = rollup.recent_audit(limit=10)
    assert [r["verb"] for r in recent] == ["b", "a"]   # newest first
    assert rollup.recent_audit(limit=1) == [recent[0]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_rollup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.rollup'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/rollup.py
"""Read-side aggregation for the Portfolio HQ toodle. Pure reads over Plan-1
engine state — composes registry + per-business state + loops + the audit log.
"""
from __future__ import annotations

from core.portfolio import loops, paths, registry, state


def business_summary(slug: str, name: str) -> dict:
    st = state.load_state(slug)
    steps = loops.load_loop(slug)
    nxt = loops.select_next_step(steps, st)
    return {
        "slug": slug,
        "name": name,
        "phase": st.get("phase", "planning"),
        "completed": len(st.get("completed_verbs", [])),
        "pending": len(st.get("pending_verbs", [])),
        "next_step": nxt.verb if nxt is not None else None,
        "total_steps": len(steps),
    }


def portfolio_overview() -> list[dict]:
    return [business_summary(b.slug, b.name) for b in registry.list_businesses()]


def recent_audit(limit: int = 50) -> list[dict]:
    rows = paths.read_jsonl(paths.data_root() / "audit.jsonl")
    return list(reversed(rows))[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_rollup.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/rollup.py tests/test_portfolio_rollup.py
git commit -m "feat(wmos): add Portfolio HQ rollup aggregation"
```

---

### Task 3: `portfolio_admin.py` — the HQ FastAPI router

**Files:**
- Create: `narai/api/routes/portfolio_admin.py`
- Test: `tests/test_portfolio_admin_api.py`

**Interfaces:**
- Consumes: `rollup.portfolio_overview`/`recent_audit`, `state.list_approvals`/`resolve_approval`, `orchestrator.control_state`/`set_enabled`/`engage_kill`/`disengage_kill`.
- Produces: `router` (`APIRouter`) with:
  - `GET  /api/narai/portfolio/overview` → `{"businesses": [...]}`
  - `GET  /api/narai/portfolio/approvals?status=pending` → `{"approvals": [...]}`
  - `POST /api/narai/portfolio/approvals/{approval_id}/resolve` body `{"status": "approved"|"rejected"}` → `{"ok": bool}`
  - `GET  /api/narai/portfolio/orchestrator` → `{"enabled": bool, "kill": bool}`
  - `POST /api/narai/portfolio/orchestrator` body `{"action": "arm"|"disarm"|"kill"|"unkill"}` → `{"enabled": bool, "kill": bool}`
  - `GET  /api/narai/portfolio/audit?limit=50` → `{"audit": [...]}`
- Test approach: build an isolated `FastAPI()` app, `include_router(router)`, drive with `TestClient` + `X-API-Key` header (do NOT import the 15k-line `core.api`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_admin_api.py
import os
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.portfolio import state


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test-key-123")
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    from narai.api.routes.portfolio_admin import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


HEAD = {"X-API-Key": "test-key-123"}


def test_overview_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/narai/portfolio/overview").status_code == 401          # no key
    r = c.get("/api/narai/portfolio/overview", headers=HEAD)
    assert r.status_code == 200
    assert len(r.json()["businesses"]) == 10


def test_orchestrator_arm_disarm_kill(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/narai/portfolio/orchestrator", headers=HEAD).json() == {"enabled": False, "kill": False}
    armed = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "arm"}).json()
    assert armed["enabled"] is True
    killed = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "kill"}).json()
    assert killed["kill"] is True
    bad = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "nope"})
    assert bad.status_code == 400


def test_approvals_list_and_resolve(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from core.portfolio.actions import Action, ActionClass
    aid = state.queue_approval(Action("deploy", "infra", ActionClass.AMBER, [], "n8n", {}))
    pending = c.get("/api/narai/portfolio/approvals", headers=HEAD, params={"status": "pending"}).json()
    assert len(pending["approvals"]) == 1
    r = c.post(f"/api/narai/portfolio/approvals/{aid}/resolve", headers=HEAD, json={"status": "approved"})
    assert r.json() == {"ok": True}
    assert c.get("/api/narai/portfolio/approvals", headers=HEAD, params={"status": "pending"}).json()["approvals"] == []


def test_audit_endpoint(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    state.audit({"verb": "x", "status": "executed"})
    r = c.get("/api/narai/portfolio/audit", headers=HEAD, params={"limit": 10})
    assert r.status_code == 200
    assert r.json()["audit"][0]["verb"] == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_admin_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'narai.api.routes.portfolio_admin'`.

- [ ] **Step 3: Write minimal implementation**

```python
# narai/api/routes/portfolio_admin.py
"""Portfolio HQ admin API — the W-MOS Master Supervisor operator surface.

Read + control over the dormant Plan-1 engine: the 10-business rollup, the AMBER
approval queue, the orchestrator arm/disarm/kill controls, and the audit log.
Reaches NO adapter — nothing autonomous can fire from here.

All endpoints require X-API-Key == env API_KEY. Mounted at /api/narai/portfolio/*.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from core.portfolio import orchestrator, rollup, state

router = APIRouter(prefix="/api/narai/portfolio", tags=["portfolio-admin"])


def verify_admin_api_key(x_api_key: str = Header(None)) -> bool:
    """FastAPI dep: require X-API-Key matching the platform API_KEY env."""
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API not configured (API_KEY env missing)")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True


class ResolveRequest(BaseModel):
    status: str  # "approved" | "rejected"


class OrchestratorRequest(BaseModel):
    action: str  # "arm" | "disarm" | "kill" | "unkill"


@router.get("/overview")
def overview(_=Depends(verify_admin_api_key)) -> dict:
    return {"businesses": rollup.portfolio_overview()}


@router.get("/approvals")
def approvals(status: str | None = None, _=Depends(verify_admin_api_key)) -> dict:
    return {"approvals": state.list_approvals(status)}


@router.post("/approvals/{approval_id}/resolve")
def resolve(approval_id: str, req: ResolveRequest, _=Depends(verify_admin_api_key)) -> dict:
    if req.status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be 'approved' or 'rejected'")
    return {"ok": state.resolve_approval(approval_id, req.status)}


@router.get("/orchestrator")
def orchestrator_state(_=Depends(verify_admin_api_key)) -> dict:
    return orchestrator.control_state()


@router.post("/orchestrator")
def orchestrator_control(req: OrchestratorRequest, _=Depends(verify_admin_api_key)) -> dict:
    if req.action == "arm":
        orchestrator.set_enabled(True)
    elif req.action == "disarm":
        orchestrator.set_enabled(False)
    elif req.action == "kill":
        orchestrator.engage_kill()
    elif req.action == "unkill":
        orchestrator.disengage_kill()
    else:
        raise HTTPException(400, "action must be arm|disarm|kill|unkill")
    return orchestrator.control_state()


@router.get("/audit")
def audit(limit: int = 50, _=Depends(verify_admin_api_key)) -> dict:
    return {"audit": rollup.recent_audit(limit=limit)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_admin_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add narai/api/routes/portfolio_admin.py tests/test_portfolio_admin_api.py
git commit -m "feat(wmos): add Portfolio HQ admin router"
```

---

### Task 4: Mount the router + serve route + Command Center card

**Files:**
- Modify: `core/api.py` (mount near line 15100; serve route near line 1665)
- Modify: `frontend/admin/index.html` (add a card in the `.grid`)
- Test: `tests/test_portfolio_mount.py`

**Interfaces:**
- Consumes: `narai.api.routes.portfolio_admin.router`; the existing `ROOT`, `_API_KEY`, `HTMLResponse` symbols in `core/api.py`.
- Produces: `GET /admin/portfolio` (HTML) and the mounted `/api/narai/portfolio/*` endpoints reachable on the real `core.api.app`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_mount.py
import os


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_portfolio_html_served(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/admin/portfolio")
    assert r.status_code == 200
    assert "W-MOS" in r.text or "Portfolio" in r.text


def test_portfolio_router_mounted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/api/narai/portfolio/overview", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    assert len(r.json()["businesses"]) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_mount.py -v`
Expected: FAIL — `/admin/portfolio` returns 404 and `/api/narai/portfolio/overview` returns 404 (not yet mounted).

- [ ] **Step 3a: Add the mount block** in `core/api.py` immediately after the SiteBoost mount (after the block ending at line ~15104, the `except ... siteboost_admin router skipped` line). Insert:

```python
    # Portfolio HQ admin API — W-MOS Master Supervisor operator surface
    try:
        from narai.api.routes.portfolio_admin import router as _portfolio_admin_rt
        app.include_router(_portfolio_admin_rt)                  # /api/narai/portfolio/*
    except Exception as _pf_exc:
        logging.getLogger("api").warning(f"portfolio_admin router skipped: {_pf_exc}")
```

- [ ] **Step 3b: Add the serve route** in `core/api.py` immediately after `serve_siteboost_admin` (after line ~1684). Insert:

```python
@app.get("/admin/portfolio", response_class=HTMLResponse)
async def serve_portfolio_admin():
    """Portfolio HQ — W-MOS Master Supervisor control panel. Shows the 10-business
    rollup, the AMBER approval queue, the orchestrator arm/kill controls, and the
    audit log. API at /api/narai/portfolio/*. Auth via X-API-Key.
    """
    path = ROOT / "frontend" / "admin" / "portfolio.html"
    if not path.exists():
        return HTMLResponse("<h1>portfolio.html not found</h1>", status_code=404)
    html = path.read_text(encoding="utf-8")
    if _API_KEY:
        sanitized = "".join(c for c in _API_KEY if 32 <= ord(c) <= 126).strip()
        html = html.replace("'%%API_KEY%%'", f"'{sanitized}'")
    return HTMLResponse(html, headers={"Cache-Control": "no-store, no-cache"})
```

- [ ] **Step 3c: Add the Command Center card** in `frontend/admin/index.html`, inside the `.grid` (after the SiteBoost card at line ~123). Insert:

```html
    <a class="card" href="/admin/portfolio">
      <span class="icon">🛰️</span>
      <div class="title">Portfolio HQ (W-MOS)</div>
      <div class="desc">Master Supervisor for the 10-business open-source portfolio: rollup, AMBER approval queue, orchestrator arm/kill, audit. Engine is dormant until armed.</div>
      <span class="badge">Live · API_KEY</span>
    </a>
```

- [ ] **Step 3d: Create a minimal placeholder `frontend/admin/portfolio.html`** so the serve route returns 200 (Task 5 replaces it with the full dashboard):

```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Portfolio HQ · W-MOS</title></head>
<body><h1>W-MOS Portfolio HQ</h1><p>Dashboard loading…</p><script>const K='%%API_KEY%%';</script></body></html>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_mount.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add core/api.py frontend/admin/index.html frontend/admin/portfolio.html tests/test_portfolio_mount.py
git commit -m "feat(wmos): mount Portfolio HQ router + serve route + Command Center card"
```

---

### Task 5: Portfolio HQ dashboard HTML

**Files:**
- Modify: `frontend/admin/portfolio.html` (replace the Task-4 placeholder with the full dashboard)
- Test: `tests/test_portfolio_html.py`

**Interfaces:**
- Consumes: the `/api/narai/portfolio/*` endpoints (Task 3); the `%%API_KEY%%` injection (Task 4 serve route).
- Produces: a single-file vanilla-JS dashboard with tabs Overview / Approvals / Orchestrator / Audit.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_html.py
from pathlib import Path

HTML = Path("frontend/admin/portfolio.html")


def test_dashboard_has_required_structure():
    text = HTML.read_text(encoding="utf-8")
    # injection hook + the four tab panels + the fetch wrapper
    assert "'%%API_KEY%%'" in text
    for marker in ['data-tab="overview"', 'data-tab="approvals"',
                   'data-tab="orchestrator"', 'data-tab="audit"']:
        assert marker in text, marker
    assert "/api/narai/portfolio/overview" in text
    assert "X-API-Key" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_html.py -v`
Expected: FAIL (placeholder lacks the tab markers / endpoints).

- [ ] **Step 3: Replace `frontend/admin/portfolio.html`** with the full dashboard:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio HQ · W-MOS</title>
<style>
:root{--bg:#0a0a0a;--panel:#111;--panel-2:#1a1a1a;--border:#262626;--text:#fafafa;
  --muted:#94a3b8;--accent:#6366f1;--accent-bg:rgba(99,102,241,.12);--green:#10b981;
  --red:#ef4444;--yellow:#f59e0b;--radius:8px;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
  font-family:system-ui,Inter,sans-serif;font-size:14px}
.topbar{background:var(--panel);border-bottom:1px solid var(--border);padding:12px 24px;
  display:flex;justify-content:space-between;align-items:center}
.brand{font-weight:700;display:flex;align-items:center;gap:10px}
.brand .pulse{width:8px;height:8px;background:var(--green);border-radius:50%}
.topnav{display:flex;gap:4px}
.tab{padding:8px 14px;color:var(--muted);background:transparent;border:0;border-radius:6px;
  font-weight:500;cursor:pointer;font-size:.9rem}
.tab.active{color:var(--text);background:var(--accent-bg)}
.wrap{padding:24px;max-width:1100px;margin:0 auto}
.panel{display:none}.panel.active{display:block}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px;margin-bottom:12px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 10px;
  border-bottom:1px solid var(--border)}th{color:var(--muted);font-weight:600}
.btn{padding:8px 14px;border:1px solid var(--border);background:var(--panel-2);
  color:var(--text);border-radius:6px;cursor:pointer;font-weight:600}
.btn.accent{background:var(--accent);border-color:var(--accent)}
.btn.danger{background:var(--red);border-color:var(--red)}
.pill{padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:600}
.pill.on{background:rgba(16,185,129,.15);color:var(--green)}
.pill.off{background:rgba(148,163,184,.15);color:var(--muted)}
.pill.kill{background:rgba(239,68,68,.15);color:var(--red)}
#error{background:rgba(239,68,68,.12);color:#fca5a5;padding:10px 24px;display:none}
.muted{color:var(--muted)}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand"><span class="pulse"></span> Portfolio HQ · W-MOS</div>
  <div class="topnav">
    <button class="tab active" data-tab="overview">Overview</button>
    <button class="tab" data-tab="approvals">Approvals</button>
    <button class="tab" data-tab="orchestrator">Orchestrator</button>
    <button class="tab" data-tab="audit">Audit</button>
  </div>
</div>
<div id="error"></div>
<div class="wrap">
  <section class="panel active" data-panel="overview">
    <div class="card"><strong>Portfolio</strong> — 10 open-source businesses. Revenue $0 (greenfield).</div>
    <div class="card"><table id="ov-table"><thead><tr><th>Business</th><th>Phase</th>
      <th>Next step</th><th>Done</th><th>Pending</th><th>Steps</th></tr></thead>
      <tbody id="ov-body"><tr><td colspan="6" class="muted">Loading…</td></tr></tbody></table></div>
  </section>
  <section class="panel" data-panel="approvals">
    <div class="card"><strong>AMBER approval queue</strong> — actions waiting for one-click approval.</div>
    <div class="card"><table><thead><tr><th>Business</th><th>Verb</th><th>Class</th><th></th></tr></thead>
      <tbody id="ap-body"><tr><td colspan="4" class="muted">Loading…</td></tr></tbody></table></div>
  </section>
  <section class="panel" data-panel="orchestrator">
    <div class="card">
      <strong>Master Supervisor</strong>
      <p>Status: <span id="orch-enabled" class="pill off">…</span>
         <span id="orch-kill" class="pill off">…</span></p>
      <p class="muted">Dormant by default. Arming lets the sweep tick; kill halts everything.</p>
      <button class="btn accent" onclick="orch('arm')">Arm</button>
      <button class="btn" onclick="orch('disarm')">Disarm</button>
      <button class="btn danger" onclick="orch('kill')">KILL</button>
      <button class="btn" onclick="orch('unkill')">Clear kill</button>
    </div>
  </section>
  <section class="panel" data-panel="audit">
    <div class="card"><strong>Audit log</strong> — every engine action, newest first.</div>
    <div class="card"><table><thead><tr><th>When</th><th>Business</th><th>Verb</th><th>Status</th></tr></thead>
      <tbody id="au-body"><tr><td colspan="4" class="muted">Loading…</td></tr></tbody></table></div>
  </section>
</div>
<script>
const API='/api/narai/portfolio';
const INJECTED='%%API_KEY%%';
function key(){
  if(INJECTED && INJECTED!=='%%API_KEY%%') return INJECTED.replace(/[^ -~]/g,'').trim();
  let k=sessionStorage.getItem('wmos_key');
  if(!k){k=prompt('Paste platform admin API_KEY:');if(k)sessionStorage.setItem('wmos_key',k.trim());}
  return (k||'').replace(/[^ -~]/g,'').trim();
}
function err(m){const e=document.getElementById('error');e.textContent='⚠ '+m;e.style.display='block';
  setTimeout(()=>e.style.display='none',8000);}
async function api(path,opts={}){
  const res=await fetch(API+path,{...opts,headers:{'X-API-Key':key(),
    'Content-Type':'application/json',...(opts.headers||{})}});
  if(res.status===401){sessionStorage.removeItem('wmos_key');err('API key rejected (401) — refresh');throw new Error('401');}
  if(!res.ok){const t=await res.text();err(path+' → '+res.status+': '+t.slice(0,140));throw new Error(res.status);}
  return res.json();
}
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
async function loadOverview(){
  const {businesses}=await api('/overview');
  document.getElementById('ov-body').innerHTML=businesses.map(b=>
    `<tr><td>${esc(b.name)}</td><td>${esc(b.phase)}</td><td>${esc(b.next_step||'—')}</td>
     <td>${b.completed}</td><td>${b.pending}</td><td>${b.total_steps}</td></tr>`).join('');
}
async function loadApprovals(){
  const {approvals}=await api('/approvals?status=pending');
  const body=document.getElementById('ap-body');
  body.innerHTML = approvals.length ? approvals.map(a=>
    `<tr><td>${esc(a.business)}</td><td>${esc(a.verb)}</td><td>${esc(a.action_class)}</td>
     <td><button class="btn accent" onclick="resolve('${esc(a.id)}','approved')">Approve</button>
         <button class="btn danger" onclick="resolve('${esc(a.id)}','rejected')">Reject</button></td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">No pending approvals.</td></tr>';
}
async function resolve(id,status){await api('/approvals/'+id+'/resolve',{method:'POST',body:JSON.stringify({status})});loadApprovals();}
async function loadOrchestrator(){
  const s=await api('/orchestrator');
  const e=document.getElementById('orch-enabled'),k=document.getElementById('orch-kill');
  e.textContent=s.enabled?'ARMED':'DORMANT';e.className='pill '+(s.enabled?'on':'off');
  k.textContent=s.kill?'KILLED':'kill clear';k.className='pill '+(s.kill?'kill':'off');
}
async function orch(action){await api('/orchestrator',{method:'POST',body:JSON.stringify({action})});loadOrchestrator();}
async function loadAudit(){
  const {audit}=await api('/audit?limit=50');
  document.getElementById('au-body').innerHTML = audit.length ? audit.map(a=>
    `<tr><td class="muted">${esc(a.at||'')}</td><td>${esc(a.business||'—')}</td>
     <td>${esc(a.verb)}</td><td>${esc(a.status)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">No audit entries yet.</td></tr>';
}
const LOADERS={overview:loadOverview,approvals:loadApprovals,orchestrator:loadOrchestrator,audit:loadAudit};
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  const name=t.dataset.tab;
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===t));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.dataset.panel===name));
  LOADERS[name]();
}));
loadOverview();
</script>
</body>
</html>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_html.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Verify the full toodle loads end-to-end + commit**

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_*.py -q
git add frontend/admin/portfolio.html tests/test_portfolio_html.py
git commit -m "feat(wmos): Portfolio HQ dashboard UI (overview/approvals/orchestrator/audit)"
```

Expected: full `test_portfolio_*` suite green.

---

## Self-Review

**1. Spec coverage (spec §3.1 HQ surface, §5 HQ tabs):**
- `/admin/portfolio` HQ surface (§3.1) → Tasks 3/4/5. ✅
- §5 tabs Overview / Approvals / Orchestrator / Audit → Task 5 (UI) over Task 3 (API). ✅ (Council tab from §5 is deferred — it's a view over the same data and adds no new engine capability; noted in Out-of-Scope.)
- Orchestrator arm/disarm/kill control (§5) → Task 1 (engine) + Task 3 (API) + Task 5 (UI). ✅
- Approval queue list + resolve (§2/§5) → Task 3 reuses `state.list_approvals`/`resolve_approval`. ✅

**2. Placeholder scan:** No TBD/TODO. Every code step shows complete code. The Task-4 `portfolio.html` placeholder is intentional and explicitly replaced in Task 5. ✅

**3. Type consistency:** `orchestrator.control_state()`/`set_enabled`/`engage_kill`/`disengage_kill` (Task 1) are the exact names called in Task 3. `rollup.portfolio_overview`/`recent_audit` (Task 2) match Task 3 calls. `state.list_approvals`/`resolve_approval`/`queue_approval`/`audit` are Plan-1 signatures used unchanged. Router paths in Task 3 match the URLs asserted in Tasks 3/4 tests and called in Task 5 JS. ✅

---

## Out of Scope (future plans)

- **Per-business Build Cockpits** (`/admin/portfolio/<slug>`) + their dispatch/tick buttons — deferred to **Plan 3**, bundled with loop-seeding + real adapters (they are empty until those exist).
- **Council tab** (CEO/CTO/CFO/CMO views) — a later view over the same rollup data.
- **Budget ceiling editing UI** and **tick-cadence control** — Plan 3/4.
- **Arming the scheduler in production** (`start_worker` wired into daemon boot) — Plan 4; also the `approvals.jsonl` write-race fix belongs there.
