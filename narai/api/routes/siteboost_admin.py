"""
SiteBoost admin API — operator surface for the local-prospect outbound product.

All endpoints require X-API-Key header matching env API_KEY (same pattern as
shopify_admin.py). Mounted at /api/narai/siteboost/*.

Endpoints:
    GET  /api/narai/siteboost/dashboard       — combined status snapshot
    GET  /api/narai/siteboost/runs            — list past campaign runs
    GET  /api/narai/siteboost/runs/{run_id}   — detail of one run
    POST /api/narai/siteboost/scan            — kick off a new scan (background)
    GET  /api/narai/siteboost/scan/{task_id}  — poll a running scan
    POST /api/narai/siteboost/selftest        — run the 49-check selftest
    GET  /api/narai/siteboost/sequences/{run_id}  — list email sequences in a run
    POST /api/narai/siteboost/state/block         — add email/domain to blocklist
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("siteboost_admin")
router = APIRouter(prefix="/api/narai/siteboost", tags=["siteboost-admin"])

# Repo root: this file is at narai/api/routes/, so go up 3
ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = ROOT / "data" / "launches" / "siteboost" / "runs"
SCANS_DIR = ROOT / "data" / "launches" / "siteboost" / "scans"

# In-memory task registry. Each task = {status, started_at, ended_at, result, log}.
# For a single-instance admin surface this is sufficient. If you horizontal-scale,
# swap for Redis/Supabase later — same dict shape.
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


# ── Auth (same pattern as shopify_admin) ────────────────────────────────────

def verify_admin_api_key(x_api_key: str = Header(None)) -> bool:
    """FastAPI dep: require X-API-Key matching the platform API_KEY env."""
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API not configured (API_KEY env missing)")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True


# ── Models ──────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    location: str = Field(..., min_length=3, max_length=120,
                          description="City+state or ZIP. US only.")
    radius_m: int = Field(5000, ge=500, le=50000)
    categories: Optional[list[str]] = None
    limit: int = Field(30, ge=1, le=200)
    live: bool = False
    """If False (default), runs dry-run with fake fixtures (no API cost)."""


class BlockRequest(BaseModel):
    email: Optional[str] = Field(None, description="Single email to block")
    domain: Optional[str] = Field(None, description="Domain to block")


# ── Helpers ─────────────────────────────────────────────────────────────────

_SAFE_LOC_RE = re.compile(r"^[A-Za-z0-9 ,.'-]{3,120}$")
_SAFE_CAT_RE = re.compile(r"^[a-z0-9_]{2,40}$")
_SAFE_RUN_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$")


def _validate_location(loc: str) -> str:
    """Reject anything that's not a plausible US location string."""
    loc = loc.strip()
    if not _SAFE_LOC_RE.match(loc):
        raise HTTPException(400, f"Invalid location format: {loc!r}")
    return loc


def _validate_run_id(run_id: str) -> str:
    """Prevent path traversal — only allow well-formed run-id slugs."""
    run_id = run_id.strip()
    if not _SAFE_RUN_RE.match(run_id):
        raise HTTPException(400, f"Invalid run_id: {run_id!r}")
    return run_id


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _list_runs() -> list[dict]:
    """Enumerate past campaign runs."""
    if not RUNS_DIR.exists():
        return []
    out = []
    for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        manifest = run_dir / "03-previews-manifest.json"
        sequences = run_dir / "04-sequences.json"
        report = run_dir / "05-report.md"
        m = _read_json(manifest) if manifest.exists() else {}
        s = _read_json(sequences) if sequences.exists() else {}
        out.append({
            "run_id": run_dir.name,
            "location": s.get("_meta", {}).get("composed_at") and run_dir.name or run_dir.name,
            "n_previews": m.get("_meta", {}).get("n_previews", 0),
            "n_sequences": len(s.get("sequences", [])),
            "has_report": report.exists(),
            "is_dry_run": m.get("_meta", {}).get("dry_run", True),
        })
    return out


# ── Background task runner ──────────────────────────────────────────────────

def _run_pipeline_task(task_id: str, location: str, radius_m: int,
                       categories: Optional[list[str]], limit: int, live: bool) -> None:
    """Run the local_prospect_run.py CLI in a subprocess, capture log."""
    with _TASKS_LOCK:
        _TASKS[task_id]["status"] = "running"

    cmd: list[str] = [".venv/bin/python3", "scripts/local_prospect_run.py",
                      "--all", "--location", location,
                      "--radius", str(radius_m), "--limit", str(limit)]
    if categories:
        # Validate every category against the safe pattern — no shell-meta possible
        safe = [c for c in categories if _SAFE_CAT_RE.match(c)]
        if safe:
            cmd.extend(["--categories", ",".join(safe)])
    if live:
        cmd.append("--live")

    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
        out = proc.stdout[-4000:] if proc.stdout else ""
        err = proc.stderr[-4000:] if proc.stderr else ""
        with _TASKS_LOCK:
            _TASKS[task_id].update({
                "status": "succeeded" if proc.returncode == 0 else "failed",
                "ended_at": time.time(),
                "exit_code": proc.returncode,
                "stdout_tail": out,
                "stderr_tail": err,
            })
    except subprocess.TimeoutExpired:
        with _TASKS_LOCK:
            _TASKS[task_id].update({
                "status": "failed", "ended_at": time.time(),
                "stderr_tail": "Pipeline exceeded 600s timeout",
            })
    except Exception as e:
        with _TASKS_LOCK:
            _TASKS[task_id].update({
                "status": "failed", "ended_at": time.time(),
                "stderr_tail": f"{type(e).__name__}: {e}",
            })


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(_=Depends(verify_admin_api_key)) -> dict:
    """Combined snapshot — what the operator sees at first glance."""
    try:
        from core import siteboost_state
        state_stats = siteboost_state.stats()
    except Exception:
        state_stats = {}

    runs = _list_runs()

    # env/DNS check — call siteboost_status.py in JSON mode
    env_status: dict[str, Any] = {}
    try:
        proc = subprocess.run(
            [".venv/bin/python3", "scripts/siteboost_status.py", "--json"],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
        if proc.returncode in (0, 1) and proc.stdout:
            env_status = json.loads(proc.stdout)
    except Exception as e:
        env_status = {"error": str(e)}

    return {
        "state": state_stats,
        "runs_count": len(runs),
        "latest_run": runs[0] if runs else None,
        "env": env_status.get("env", {}),
        "dns": env_status.get("dns", {}),
        "blockers": env_status.get("blockers", []),
    }


@router.get("/runs")
def list_runs(_=Depends(verify_admin_api_key)) -> dict:
    return {"runs": _list_runs()}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, _=Depends(verify_admin_api_key)) -> dict:
    run_id = _validate_run_id(run_id)
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(404, f"Run {run_id} not found")

    manifest = _read_json(run_dir / "03-previews-manifest.json")
    sequences = _read_json(run_dir / "04-sequences.json")
    report_md = (run_dir / "05-report.md").read_text() if (run_dir / "05-report.md").exists() else ""

    return {
        "run_id": run_id,
        "previews_manifest": manifest,
        "sequences_meta": sequences.get("_meta", {}),
        "n_sequences": len(sequences.get("sequences", [])),
        "report_md": report_md,
    }


@router.get("/sequences/{run_id}")
def list_sequences(run_id: str, _=Depends(verify_admin_api_key)) -> dict:
    """Return all 3-touch sequences for a run — for review before sending."""
    run_id = _validate_run_id(run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    data = _read_json(seq_file)
    return {"sequences": data.get("sequences", []), "meta": data.get("_meta", {})}


@router.post("/scan")
def start_scan(req: ScanRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Kick off a scan in the background. Returns task_id for polling."""
    location = _validate_location(req.location)
    task_id = uuid.uuid4().hex[:12]

    with _TASKS_LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "started_at": time.time(),
            "ended_at": None,
            "location": location,
            "live": req.live,
            "limit": req.limit,
        }

    t = threading.Thread(
        target=_run_pipeline_task, daemon=True,
        args=(task_id, location, req.radius_m, req.categories, req.limit, req.live),
    )
    t.start()
    return {"task_id": task_id, "status": "queued",
            "poll_url": f"/api/narai/siteboost/scan/{task_id}"}


@router.get("/scan/{task_id}")
def scan_status(task_id: str, _=Depends(verify_admin_api_key)) -> dict:
    if not re.match(r"^[0-9a-f]{12}$", task_id):
        raise HTTPException(400, "Invalid task_id format")
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
    if not t:
        raise HTTPException(404, f"Task {task_id} not found")
    return t


@router.post("/selftest")
def run_selftest(_=Depends(verify_admin_api_key)) -> dict:
    """Run the 49-check selftest. Returns pass/fail counts + summary."""
    try:
        proc = subprocess.run(
            ["bash", "scripts/siteboost_selftest.sh"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
            env={**os.environ, "NO_COLOR": "1"},  # strip ANSI codes for clean parsing
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "selftest exceeded 120s timeout"}

    out = proc.stdout or ""
    # Parse the summary line: "✓ ALL CHECKS PASSED  (49/49)" or "✗ N CHECK(S) FAILED  (X/Y passed)"
    passed = failed = total = 0
    m = re.search(r"\((\d+)/(\d+)\)", out)
    if m:
        passed, total = int(m.group(1)), int(m.group(2))
        failed = total - passed
    return {
        "ok": proc.returncode == 0,
        "passed": passed, "failed": failed, "total": total,
        "exit_code": proc.returncode,
        "tail": out[-3000:],
    }


@router.post("/state/block")
def block_email_or_domain(req: BlockRequest, _=Depends(verify_admin_api_key)) -> dict:
    if not req.email and not req.domain:
        raise HTTPException(400, "Provide email or domain")
    try:
        from core import siteboost_state
    except Exception as e:
        raise HTTPException(500, f"siteboost_state import failed: {e}")

    result: dict[str, Any] = {}
    # block_email / block_domain interfaces vary slightly — best-effort detection
    if req.email and hasattr(siteboost_state, "block_email"):
        siteboost_state.block_email(req.email)
        result["blocked_email"] = req.email
    if req.domain and hasattr(siteboost_state, "block_domain"):
        siteboost_state.block_domain(req.domain)
        result["blocked_domain"] = req.domain
    if not result:
        raise HTTPException(500, "siteboost_state has no block_email/block_domain methods")
    return result
