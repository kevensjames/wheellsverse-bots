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
import sys
import threading
import time
import uuid

import requests
from pathlib import Path
from typing import Any, Optional

# Activity log — appends to events.jsonl on the persistent volume in prod.
# Defensive fallback noop so the app never breaks if the module fails to import.
try:
    from core.siteboost_events import log_event, get_recent_events
except Exception:
    def log_event(*args, **kwargs): pass  # type: ignore
    def get_recent_events(limit: int = 100): return []  # type: ignore

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("siteboost_admin")
router = APIRouter(prefix="/api/narai/siteboost", tags=["siteboost-admin"])

# Repo root: this file is at narai/api/routes/, so go up 3
ROOT = Path(__file__).resolve().parents[3]
# Override via env vars to use the persistent Railway volume in production.
# Without these, runs + scans live on the container's ephemeral filesystem and
# get wiped on every redeploy — which would break every preview URL in every
# already-sent cold email. Set SITEBOOST_RUNS_PATH=/var/data/siteboost/runs etc.
RUNS_DIR = Path(os.getenv("SITEBOOST_RUNS_PATH",
                          str(ROOT / "data" / "launches" / "siteboost" / "runs")))
SCANS_DIR = Path(os.getenv("SITEBOOST_SCANS_PATH",
                            str(ROOT / "data" / "launches" / "siteboost" / "scans")))

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


class SendRequest(BaseModel):
    """Trigger real outbound sends to Instantly. Multi-gated for safety:
    (1) X-API-Key admin auth, (2) explicit confirm literal, (3) hard daily cap.
    """
    run_id: str = Field(..., min_length=10, max_length=80,
                        description="Run slug like '2026-06-12-hyannis-ma'")
    confirm: str = Field(..., description="Must equal exactly 'YES-I-CONFIRM-REAL-SEND'")
    max_per_day: int = Field(20, ge=1, le=100,
                              description="Hard cap per call. Default 20 keeps blasts small.")


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

    cmd: list[str] = [sys.executable, "scripts/local_prospect_run.py",
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
        log_event("scan.succeeded" if proc.returncode == 0 else "scan.failed",
                  task_id=task_id, location=location, exit_code=proc.returncode)
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
            [sys.executable, "scripts/siteboost_status.py", "--json"],
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

    # Scan file lives in SCANS_DIR with the same slug as the run_id —
    # surface its _meta so operators can see rejection breakdown without SSH.
    scan_file = SCANS_DIR / f"{run_id}.json"
    scan_meta = _read_json(scan_file).get("_meta", {}) if scan_file.exists() else {}
    rejected_sample = []
    if scan_file.exists():
        scan_data = _read_json(scan_file)
        rejected_sample = scan_data.get("rejected", [])[:10]

    return {
        "run_id": run_id,
        "previews_manifest": manifest,
        "sequences_meta": sequences.get("_meta", {}),
        "n_sequences": len(sequences.get("sequences", [])),
        "report_md": report_md,
        "scan_meta": scan_meta,
        "rejected_sample": rejected_sample,
    }


@router.get("/runs/{run_id}/prospects")
def list_run_prospects(run_id: str, _=Depends(verify_admin_api_key)) -> dict:
    """Return ALL prospects from a run (targetable + rejected) with full inspector detail.

    Merges scan file (raw probe data) + enriched file (Hunter results) + previews_manifest
    (slug + preview URL) so the operator can drill into any prospect from the dashboard.
    """
    run_id = _validate_run_id(run_id)
    scan_file = SCANS_DIR / f"{run_id}.json"
    enriched_file = SCANS_DIR / f"{run_id}-enriched.json"
    mani_file = RUNS_DIR / run_id / "03-previews-manifest.json"

    scan = _read_json(scan_file) if scan_file.exists() else {}
    enriched = _read_json(enriched_file) if enriched_file.exists() else {}
    mani = _read_json(mani_file) if mani_file.exists() else {}

    # Index enriched by name (lossless lookup)
    enr_by_name = {e["name"]: e for e in enriched.get("enriched", [])}
    prev_by_name = {p["name"]: p for p in mani.get("previews", [])}

    out_targetable = []
    for p in scan.get("targetable", []):
        name = p.get("name", "")
        enr = enr_by_name.get(name, {})
        prev = prev_by_name.get(name, {})
        out_targetable.append({
            **p,
            "enriched_email": (enr.get("contact") or {}).get("email", ""),
            "enriched_first_name": (enr.get("contact") or {}).get("first_name", ""),
            "enriched_last_name": (enr.get("contact") or {}).get("last_name", ""),
            "enriched_confidence": (enr.get("contact") or {}).get("confidence", 0),
            "preview_slug": prev.get("slug", ""),
            "preview_url": prev.get("preview_url", ""),
        })

    return {
        "run_id": run_id,
        "targetable": out_targetable,
        "rejected": scan.get("rejected", []),
        "n_targetable": len(out_targetable),
        "n_rejected": len(scan.get("rejected", [])),
    }


@router.get("/runs/{run_id}/prospects/{slug}")
def get_prospect_detail(run_id: str, slug: str, _=Depends(verify_admin_api_key)) -> dict:
    """Drill into ONE specific prospect — everything we know + the email we'd send."""
    run_id = _validate_run_id(run_id)
    if not re.match(r"^[a-z0-9-]{1,80}$", slug):
        raise HTTPException(400, "Invalid slug format")

    scan_file = SCANS_DIR / f"{run_id}.json"
    enriched_file = SCANS_DIR / f"{run_id}-enriched.json"
    seq_file = RUNS_DIR / run_id / "04-sequences.json"

    scan = _read_json(scan_file) if scan_file.exists() else {}
    enriched = _read_json(enriched_file) if enriched_file.exists() else {}
    sequences = _read_json(seq_file).get("sequences", []) if seq_file.exists() else []

    # Find by slug — slugify business names locally to match
    target = None
    for p in scan.get("targetable", []):
        if _slugify(p.get("name", "")) == slug:
            target = p
            break
    if not target:
        raise HTTPException(404, f"Prospect {slug!r} not found in run {run_id}")

    contact = next(
        ((e.get("contact") or {}) for e in enriched.get("enriched", [])
         if _slugify(e.get("name", "")) == slug), {}
    )
    seq = next(
        (s for s in sequences if _slugify(s.get("business_name", "")) == slug), None
    )

    return {
        "run_id": run_id,
        "slug": slug,
        "prospect": target,
        "contact": contact,
        "sequence": seq,
        "preview_url": f"https://app.wheellsverse.com/p/{slug}",
    }


def _slugify(text: str) -> str:
    """Same algorithm as site_generator._slugify — kept in sync."""
    s = re.sub(r"[^a-zA-Z0-9-]", "-", text.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:60]


class SendTestRequest(BaseModel):
    """Send Touch 1 of a specific sequence to YOUR email instead of the prospect.
    Use this to see exactly what a prospect would receive — including the actual
    issue-aware opener, the unsub link, the CAN-SPAM footer."""
    run_id: str = Field(..., min_length=10, max_length=80)
    slug: str = Field(..., min_length=1, max_length=80)
    recipient_email: str = Field(..., min_length=5, max_length=120,
                                  description="Your own email — the test send goes here")


@router.post("/send-test")
def send_test_to_self(req: SendTestRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Send Touch 1 of a sequence to the operator's email via Resend.

    Mirrors the real send pipeline exactly — same body, same footer, same domain —
    but with the recipient address overridden. Used to validate copy before real send.
    """
    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    sequences = _read_json(seq_file).get("sequences", [])
    seq = next(
        (s for s in sequences if _slugify(s.get("business_name", "")) == req.slug), None
    )
    if not seq:
        raise HTTPException(404, f"No sequence for {req.slug} in {run_id}")

    touch1 = seq["touches"][0]
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    outbound_domain = os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com")
    if not resend_key:
        raise HTTPException(503, "RESEND_API_KEY not set")

    import requests
    payload = {
        "from": f"SiteBoost Test <siteboost@{outbound_domain}>",
        "to": [req.recipient_email],
        "subject": f"[TEST → would go to {seq.get('to_email')}] {touch1['subject']}",
        "text": touch1["body"],
    }
    r = requests.post(
        "https://api.resend.com/emails",
        json=payload,
        headers={"Authorization": f"Bearer {resend_key}"},
        timeout=20,
    )
    if r.status_code in (200, 201):
        log_event("send.test_single", run_id=run_id, slug=req.slug,
                  business=seq.get("business_name"),
                  recipient=req.recipient_email,
                  would_be=seq.get("to_email"),
                  resend_id=r.json().get("id", ""))
        return {
            "status": "sent",
            "resend_id": r.json().get("id", ""),
            "real_recipient_would_be": seq.get("to_email"),
            "your_email": req.recipient_email,
            "business": seq.get("business_name"),
            "subject": touch1["subject"],
        }
    log_event("send.test_single_failed", run_id=run_id, slug=req.slug, http=r.status_code)
    return {"status": "failed", "http": r.status_code, "body": r.text[:300]}


class SkipRequest(BaseModel):
    run_id: str = Field(..., min_length=10, max_length=80)
    slug: str = Field(..., min_length=1, max_length=80)
    skip: bool = Field(True, description="True to skip, False to re-include")


class ReviewRequest(BaseModel):
    run_id: str = Field(..., min_length=10, max_length=80)
    slug: str = Field(..., min_length=1, max_length=80)
    reviewed: bool = Field(True, description="Mark sequence as operator-reviewed")


class TestAllRequest(BaseModel):
    run_id: str = Field(..., min_length=10, max_length=80)
    recipient_email: str = Field(..., min_length=5, max_length=120,
                                  description="Operator's email — every Touch 1 goes here")
    only_unreviewed: bool = Field(False,
                                   description="If True, only sends sequences NOT yet marked reviewed")


@router.post("/sequences/review")
def toggle_sequence_review(req: ReviewRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Mark a sequence as operator-reviewed (or un-reviewed).

    Used in the UI to track which prospects you've already QA'd. Doesn't affect
    sending behavior — purely a status flag for operator workflow.
    """
    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    data = _read_json(seq_file)
    found = False
    for s in data.get("sequences", []):
        if _slugify(s.get("business_name", "")) == req.slug:
            s["reviewed"] = req.reviewed
            s["reviewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if req.reviewed else ""
            found = True
            break
    if not found:
        raise HTTPException(404, f"No sequence for {req.slug}")
    tmp = seq_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(seq_file)
    log_event("sequence.reviewed" if req.reviewed else "sequence.unreviewed",
              run_id=run_id, slug=req.slug)
    return {"status": "ok", "slug": req.slug, "reviewed": req.reviewed}


@router.post("/send-test-all")
def send_test_all_to_self(req: TestAllRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Fire Touch 1 of every non-skipped sequence in a run to the operator's email.

    Use this to QA a batch in one go — the operator gets N emails in their inbox,
    each prefixed [TEST → would go to X@y.com] so they can quickly skim each one.

    Filters:
        - skipped sequences are excluded (operator already marked these don't-send)
        - if only_unreviewed=True, also excludes reviewed=True ones

    Rate-limited: 0.5s sleep between each Resend POST to avoid throttle.
    """
    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    sequences = _read_json(seq_file).get("sequences", [])

    targets = [s for s in sequences if not s.get("skipped")]
    if req.only_unreviewed:
        targets = [s for s in targets if not s.get("reviewed")]

    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    outbound_domain = os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com")
    if not resend_key:
        raise HTTPException(503, "RESEND_API_KEY not set")

    sent = 0
    failed: list[dict] = []
    for s in targets:
        touch1 = s["touches"][0]
        payload = {
            "from": f"SiteBoost Test <siteboost@{outbound_domain}>",
            "to": [req.recipient_email],
            "subject": f"[TEST → {s.get('to_email')}] {touch1['subject']}",
            "text": touch1["body"],
        }
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {resend_key}"},
                timeout=20,
            )
            if r.status_code in (200, 201):
                sent += 1
            else:
                failed.append({"business": s.get("business_name"), "http": r.status_code,
                                "body": r.text[:200]})
        except Exception as e:
            failed.append({"business": s.get("business_name"), "error": str(e)[:200]})
        time.sleep(0.5)

    log_event("send.test_all", run_id=run_id,
              recipient=req.recipient_email, n_targets=len(targets),
              n_sent=sent, n_failed=len(failed))
    return {
        "status": "ok",
        "run_id": run_id,
        "recipient": req.recipient_email,
        "n_targets": len(targets),
        "n_sent": sent,
        "n_failed": len(failed),
        "failed_detail": failed[:10],
    }


@router.post("/sequences/skip")
def toggle_sequence_skip(req: SkipRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Mark a specific prospect's sequence as skipped — it won't be sent.

    Adds 'skipped': true to the sequence object in 04-sequences.json. The send
    pipeline filters these out. Use to remove low-quality prospects from a batch
    without re-running the whole pipeline.
    """
    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    data = _read_json(seq_file)
    found = False
    for s in data.get("sequences", []):
        if _slugify(s.get("business_name", "")) == req.slug:
            s["skipped"] = req.skip
            found = True
            break
    if not found:
        raise HTTPException(404, f"No sequence for {req.slug}")
    # Atomic write
    tmp = seq_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(seq_file)
    log_event("sequence.skipped" if req.skip else "sequence.unskipped",
              run_id=run_id, slug=req.slug)
    return {"status": "ok", "slug": req.slug, "skipped": req.skip}


class EditBodyRequest(BaseModel):
    run_id: str = Field(..., min_length=10, max_length=80)
    slug: str = Field(..., min_length=1, max_length=80)
    touch_index: int = Field(..., ge=0, le=2, description="0, 1, or 2 for Touch 1/2/3")
    subject: Optional[str] = Field(None, max_length=250)
    body: Optional[str] = Field(None, max_length=10000)


@router.post("/sequences/edit")
def edit_sequence_body(req: EditBodyRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Edit a specific touch's subject or body for a specific prospect."""
    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    data = _read_json(seq_file)
    for s in data.get("sequences", []):
        if _slugify(s.get("business_name", "")) == req.slug:
            touches = s.get("touches", [])
            if req.touch_index >= len(touches):
                raise HTTPException(400, "touch_index out of range")
            if req.subject is not None:
                touches[req.touch_index]["subject"] = req.subject
            if req.body is not None:
                touches[req.touch_index]["body"] = req.body
            touches[req.touch_index]["edited"] = True
            tmp = seq_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(seq_file)
            return {"status": "ok", "slug": req.slug, "touch_index": req.touch_index}
    raise HTTPException(404, f"No sequence for {req.slug}")


@router.get("/costs")
def get_cost_tracker(_=Depends(verify_admin_api_key)) -> dict:
    """Lightweight running-total cost tracker. Pulls totals from scan + send activity.

    Heuristic estimates (per scan / per send) since none of the providers expose
    realtime spend via API. Numbers come from each provider's published rate cards.
    """
    # Iterate every scan run and sum up
    runs = _list_runs()
    total_places_calls = 0
    total_hunter_calls = 0
    total_openai_calls = 0
    total_sends = 0
    for r in runs:
        run_id = r["run_id"]
        scan_file = SCANS_DIR / f"{run_id}.json"
        if scan_file.exists():
            d = _read_json(scan_file)
            n_total = d.get("_meta", {}).get("n_total", 0)
            # Google Places: ~3 calls per prospect (geocode + nearby + details)
            total_places_calls += n_total * 3
        enriched_file = SCANS_DIR / f"{run_id}-enriched.json"
        if enriched_file.exists():
            d = _read_json(enriched_file)
            n_targetable = d.get("_meta", {}).get("n_targetable", 0)
            # Hunter: 1 domain-search call per targetable
            total_hunter_calls += n_targetable
            # OpenAI: 1 call per generated preview (LLM personalize)
            total_openai_calls += d.get("_meta", {}).get("n_enriched", 0)

    cost_places = total_places_calls * 0.005  # ~$5 per 1000
    cost_hunter = max(0, total_hunter_calls - 50) * 0.034  # 50 free/mo then ~$0.034 each
    cost_openai = total_openai_calls * 0.002  # gpt-4o-mini ~$0.002 avg per request
    cost_total = cost_places + cost_hunter + cost_openai

    return {
        "places_calls": total_places_calls,
        "hunter_calls": total_hunter_calls,
        "openai_calls": total_openai_calls,
        "total_sends": total_sends,
        "cost_places_usd": round(cost_places, 4),
        "cost_hunter_usd": round(cost_hunter, 4),
        "cost_openai_usd": round(cost_openai, 4),
        "cost_total_usd": round(cost_total, 4),
        "note": "Heuristic estimates from public rate cards. Cross-check with provider dashboards monthly.",
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


@router.post("/send")
def start_send(req: SendRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Dispatch a run's sequences to Instantly. REAL OUTBOUND — multi-gated.

    Safety gates layered:
        1. X-API-Key admin auth (verify_admin_api_key dep)
        2. confirm field MUST equal 'YES-I-CONFIRM-REAL-SEND' (no typo tolerance)
        3. Run must exist with 04-sequences.json on disk
        4. max_per_day hard-capped at 100 by Pydantic (default 20)
        5. send_sequences() itself requires confirm=True AND live=True AND
           non-dangerous outbound domain AND INSTANTLY_API_KEY+CAMPAIGN_ID set

    Async — returns task_id immediately; poll /scan/{task_id} for status.
    """
    if req.confirm != "YES-I-CONFIRM-REAL-SEND":
        raise HTTPException(
            400,
            "confirm field must equal 'YES-I-CONFIRM-REAL-SEND' literally"
        )

    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences found for run {run_id}")

    task_id = uuid.uuid4().hex[:12]
    with _TASKS_LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "kind": "send",
            "status": "queued",
            "started_at": time.time(),
            "ended_at": None,
            "run_id": run_id,
            "max_per_day": req.max_per_day,
        }

    def _do_send() -> None:
        with _TASKS_LOCK:
            _TASKS[task_id]["status"] = "running"
        try:
            from core.cold_outreach import send_sequences
            result = send_sequences(
                seq_file, confirm=True, live=True, max_per_day=req.max_per_day,
            )
            with _TASKS_LOCK:
                _TASKS[task_id]["status"] = (
                    "succeeded" if result.get("status") == "ok" else "blocked"
                )
                _TASKS[task_id]["ended_at"] = time.time()
                _TASKS[task_id]["result"] = result
        except Exception as exc:
            with _TASKS_LOCK:
                _TASKS[task_id]["status"] = "failed"
                _TASKS[task_id]["ended_at"] = time.time()
                _TASKS[task_id]["error"] = f"{type(exc).__name__}: {exc}"[:500]

    threading.Thread(target=_do_send, daemon=True).start()
    log_event("send.dispatched", run_id=run_id,
              task_id=task_id, max_per_day=req.max_per_day)

    return {
        "task_id": task_id,
        "status": "queued",
        "poll_url": f"/api/narai/siteboost/scan/{task_id}",
        "run_id": run_id,
        "max_per_day": req.max_per_day,
    }


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
    log_event("scan.started", task_id=task_id, location=location,
              limit=req.limit, live=req.live)
    return {"task_id": task_id, "status": "queued",
            "poll_url": f"/api/narai/siteboost/scan/{task_id}"}


class ScheduleAddRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    location: str = Field(..., min_length=3, max_length=120)
    hour: int = Field(..., ge=0, le=23,
                       description="UTC hour to fire at (0-23). Convert from local time mentally.")
    days_of_week: list[int] = Field(..., min_length=1, max_length=7,
                                      description="0=Mon, 1=Tue, ..., 6=Sun (UTC weekday)")
    radius_m: int = Field(10000, ge=500, le=50000)
    limit: int = Field(50, ge=1, le=200)
    live: bool = Field(True)


class ScheduleToggleRequest(BaseModel):
    enabled: bool


def _fire_scheduled_scan(schedule: dict) -> None:
    """Worker callback — launches a scan via the same thread pattern as /scan."""
    task_id = uuid.uuid4().hex[:12]
    location = _validate_location(schedule["location"])
    with _TASKS_LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "started_at": time.time(),
            "ended_at": None,
            "location": location,
            "live": schedule.get("live", True),
            "limit": schedule.get("limit", 50),
            "scheduled_id": schedule.get("id"),
        }
    t = threading.Thread(
        target=_run_pipeline_task, daemon=True,
        args=(task_id, location, schedule.get("radius_m", 10000),
              None, schedule.get("limit", 50), schedule.get("live", True)),
    )
    t.start()
    log_event("schedule.fired", schedule_id=schedule.get("id"),
              task_id=task_id, location=location)


def _ensure_scheduler_running() -> None:
    """Idempotent — start the scheduler worker if not already running."""
    try:
        from core.siteboost_scheduler import start_worker
        start_worker(_fire_scheduled_scan)
    except Exception as e:
        logging.getLogger("siteboost_admin").warning(f"scheduler start failed: {e}")


@router.get("/schedules")
def get_schedules(_=Depends(verify_admin_api_key)) -> dict:
    """List all configured scheduled scans."""
    _ensure_scheduler_running()
    try:
        from core.siteboost_scheduler import list_schedules
        return {"schedules": list_schedules()}
    except Exception as e:
        return {"schedules": [], "error": str(e)}


@router.post("/schedules")
def create_schedule(req: ScheduleAddRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Create a new scheduled scan.

    Once added, the background scheduler will fire it at `hour:00 UTC` on each of
    the `days_of_week`, as long as it hasn't already fired today (so a hot-restart
    doesn't trigger a double-fire). Use POST /schedules/{id}/run to fire immediately
    for testing.
    """
    _ensure_scheduler_running()
    try:
        from core.siteboost_scheduler import add_schedule
        sched = add_schedule(
            name=req.name, location=req.location,
            hour=req.hour, days_of_week=req.days_of_week,
            radius_m=req.radius_m, limit=req.limit, live=req.live,
        )
        log_event("schedule.created", schedule_id=sched["id"],
                  name=req.name, location=req.location, hour=req.hour)
        return {"status": "ok", "schedule": sched}
    except Exception as e:
        raise HTTPException(500, f"Add failed: {e!s}")


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str, _=Depends(verify_admin_api_key)) -> dict:
    if not re.match(r"^[0-9a-f]{12}$", schedule_id):
        raise HTTPException(400, "Invalid schedule id")
    try:
        from core.siteboost_scheduler import remove_schedule
        removed = remove_schedule(schedule_id)
        if removed:
            log_event("schedule.removed", schedule_id=schedule_id)
        return {"status": "ok", "removed": removed}
    except Exception as e:
        raise HTTPException(500, f"Delete failed: {e!s}")


@router.patch("/schedules/{schedule_id}/toggle")
def patch_schedule_toggle(schedule_id: str, req: ScheduleToggleRequest,
                          _=Depends(verify_admin_api_key)) -> dict:
    if not re.match(r"^[0-9a-f]{12}$", schedule_id):
        raise HTTPException(400, "Invalid schedule id")
    try:
        from core.siteboost_scheduler import toggle_schedule
        changed = toggle_schedule(schedule_id, req.enabled)
        if not changed:
            raise HTTPException(404, "Schedule not found")
        log_event("schedule.toggled", schedule_id=schedule_id, enabled=req.enabled)
        return {"status": "ok", "enabled": req.enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Toggle failed: {e!s}")


@router.post("/schedules/{schedule_id}/run")
def run_schedule_now(schedule_id: str, _=Depends(verify_admin_api_key)) -> dict:
    """Fire a saved schedule immediately, ignoring the day/hour gates.
    Useful for testing without waiting for the scheduled time."""
    if not re.match(r"^[0-9a-f]{12}$", schedule_id):
        raise HTTPException(400, "Invalid schedule id")
    try:
        from core.siteboost_scheduler import get_schedule, mark_run
        sched = get_schedule(schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")
        _fire_scheduled_scan(sched)
        mark_run(schedule_id)
        return {"status": "fired", "schedule_id": schedule_id, "location": sched["location"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Run failed: {e!s}")


class OverrideNameRequest(BaseModel):
    run_id: str = Field(..., min_length=10, max_length=80)
    slug: str = Field(..., min_length=1, max_length=80)
    first_name: str = Field(..., min_length=1, max_length=60)
    last_name: str = Field("", max_length=60)


@router.post("/sequences/override-name")
def override_sequence_name(req: OverrideNameRequest,
                            _=Depends(verify_admin_api_key)) -> dict:
    """Replace the salutation name in all 3 touches of a sequence.

    Use case: Hunter found the email but not the owner's name, so the compose
    stage defaulted to "Hi there". When the operator manually finds the owner's
    name (LinkedIn, Google), this endpoint:
        1. Updates the sequence's to_name field
        2. Finds the OLD salutation ("Hi there," or "Hi <old_name>,") in each
           touch body and replaces it with "Hi <new_first_name>,"
        3. Also updates the touch's subject if it starts with the old name

    Replacement is a surgical find-replace, not a re-render — keeps the operator's
    other edits intact. Marks each touch as edited=True for audit visibility.
    """
    run_id = _validate_run_id(req.run_id)
    if not re.match(r"^[A-Za-z][A-Za-z\s'-]{0,59}$", req.first_name.strip()):
        raise HTTPException(400, "first_name must be 1-60 chars, letters/space/'/- only")
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    data = _read_json(seq_file)

    target = None
    for s in data.get("sequences", []):
        if _slugify(s.get("business_name", "")) == req.slug:
            target = s
            break
    if not target:
        raise HTTPException(404, f"No sequence for {req.slug}")

    # Derive old first name from current to_name (or fall back to "there")
    # split() on "" returns [] — guard against IndexError on empty to_name.
    parts = (target.get("to_name") or "").split()
    old_name = parts[0] if parts else "there"
    new_first = req.first_name.strip()
    new_full = (new_first + " " + req.last_name.strip()).strip() if req.last_name.strip() else new_first

    # Update to_name
    target["to_name"] = new_full

    # Patch each touch
    n_touches = 0
    for t in target.get("touches", []):
        body = t.get("body", "")
        subject = t.get("subject", "")
        # Replace common salutation patterns. Order matters: "Hi <old_name>" first.
        patterns_to_swap = [
            (f"Hi {old_name},", f"Hi {new_first},"),
            (f"Hi {old_name}\n", f"Hi {new_first}\n"),
            (f"Hi {old_name} ", f"Hi {new_first} "),
        ]
        # Subject leading-name pattern: "{old_name} — ..."
        subj_patterns = [
            (f"{old_name} —", f"{new_first} —"),
            (f"{old_name},", f"{new_first},"),
        ]
        changed = False
        for old, new in patterns_to_swap:
            if old in body:
                body = body.replace(old, new)
                changed = True
        for old, new in subj_patterns:
            if subject.startswith(old):
                subject = new + subject[len(old):]
                changed = True
        if changed:
            t["body"] = body
            t["subject"] = subject
            t["edited"] = True
            n_touches += 1

    tmp = seq_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(seq_file)
    log_event("sequence.name_overridden", run_id=run_id, slug=req.slug,
              new_first_name=new_first, touches_updated=n_touches)
    return {
        "status": "ok",
        "slug": req.slug,
        "new_to_name": new_full,
        "old_first_name": old_name,
        "touches_updated": n_touches,
    }


class BulkSkipRequest(BaseModel):
    run_id: str = Field(..., min_length=10, max_length=80)
    slugs: list[str] = Field(..., min_length=1, max_length=500,
                              description="Up to 500 prospect slugs to skip/unskip in one call")
    skip: bool = Field(True, description="True to skip all, False to re-include all")


@router.post("/sequences/skip-bulk")
def bulk_skip_sequences(req: BulkSkipRequest,
                        _=Depends(verify_admin_api_key)) -> dict:
    """Skip or re-include MANY sequences in one call. 10-click reviews → 1 click.

    Each provided slug is validated against the same regex as single-skip; unknown
    slugs are silently skipped (operator may have a stale list). Atomic write of
    the whole sequences file at the end so partial state never lands on disk.
    """
    run_id = _validate_run_id(req.run_id)
    seq_file = RUNS_DIR / run_id / "04-sequences.json"
    if not seq_file.exists():
        raise HTTPException(404, f"No sequences for run {run_id}")
    data = _read_json(seq_file)
    slug_set = {s for s in req.slugs if re.match(r"^[a-z0-9-]{1,80}$", s)}
    touched: list[str] = []
    for s in data.get("sequences", []):
        sl = _slugify(s.get("business_name", ""))
        if sl in slug_set:
            s["skipped"] = req.skip
            touched.append(sl)
    if not touched:
        return {"status": "ok", "touched": 0, "n_requested": len(slug_set)}
    tmp = seq_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(seq_file)
    log_event("sequence.bulk_skipped" if req.skip else "sequence.bulk_unskipped",
              run_id=run_id, n_touched=len(touched), n_requested=len(slug_set))
    return {"status": "ok", "touched": len(touched), "n_requested": len(slug_set), "slugs": touched}


@router.get("/runs/{run_id}/export.csv")
def export_run_csv(run_id: str, _=Depends(verify_admin_api_key)):
    """Stream a CSV of every targetable prospect + their sequence detail.

    Use for:
      - Spreadsheet review of a whole run
      - Sharing with a teammate (drop into Google Sheets)
      - Archival before the run gets old
      - Manual outreach (copy emails into another tool)
    """
    import csv, io
    from fastapi.responses import StreamingResponse

    run_id = _validate_run_id(run_id)
    scan_file = SCANS_DIR / f"{run_id}.json"
    enriched_file = SCANS_DIR / f"{run_id}-enriched.json"
    seq_file = RUNS_DIR / run_id / "04-sequences.json"

    scan = _read_json(scan_file) if scan_file.exists() else {}
    enriched = _read_json(enriched_file) if enriched_file.exists() else {}
    sequences = _read_json(seq_file).get("sequences", []) if seq_file.exists() else []

    # Index enriched + sequences by slug for fast lookup
    enr_by_slug = {}
    for e in enriched.get("enriched", []):
        sl = _slugify(e.get("name", ""))
        enr_by_slug[sl] = e
    seq_by_slug = {}
    for s in sequences:
        sl = _slugify(s.get("business_name", ""))
        seq_by_slug[sl] = s

    # Build CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "name", "category", "address", "phone", "website",
        "website_issues", "rating", "review_count",
        "hunter_email", "hunter_first_name", "hunter_last_name", "hunter_confidence",
        "preview_url",
        "skipped", "reviewed",
        "touch1_subject", "touch2_subject", "touch3_subject",
    ])
    for p in scan.get("targetable", []):
        sl = _slugify(p.get("name", ""))
        enr = enr_by_slug.get(sl, {})
        contact = enr.get("contact") or {}
        seq = seq_by_slug.get(sl, {})
        touches = seq.get("touches", []) or []
        writer.writerow([
            p.get("name", ""),
            p.get("category", ""),
            p.get("address", ""),
            p.get("phone", ""),
            p.get("website", ""),
            ";".join(p.get("website_issues") or []),
            p.get("rating", ""),
            p.get("review_count", ""),
            contact.get("email", ""),
            contact.get("first_name", ""),
            contact.get("last_name", ""),
            contact.get("confidence", ""),
            f"https://app.wheellsverse.com/p/{sl}" if sl else "",
            "yes" if seq.get("skipped") else "",
            "yes" if seq.get("reviewed") else "",
            (touches[0].get("subject") if len(touches) > 0 else ""),
            (touches[1].get("subject") if len(touches) > 1 else ""),
            (touches[2].get("subject") if len(touches) > 2 else ""),
        ])

    buf.seek(0)
    filename = f"siteboost-{run_id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/stats")
def run_stats(run_id: str, _=Depends(verify_admin_api_key)) -> dict:
    """Quick decision-support metrics for a single run.

    Helps the operator decide "should I dispatch THIS run?" with one glance:
        - Hunter hit rate (X enriched / Y targetable)
        - Top 5 detected website issues
        - Top 5 business categories
        - Average Hunter confidence
        - Skipped + reviewed counts
    """
    run_id = _validate_run_id(run_id)
    scan_file = SCANS_DIR / f"{run_id}.json"
    enriched_file = SCANS_DIR / f"{run_id}-enriched.json"
    seq_file = RUNS_DIR / run_id / "04-sequences.json"

    scan = _read_json(scan_file) if scan_file.exists() else {}
    enriched = _read_json(enriched_file) if enriched_file.exists() else {}
    sequences = _read_json(seq_file).get("sequences", []) if seq_file.exists() else []

    targetable = scan.get("targetable", [])
    enriched_list = enriched.get("enriched", [])

    # Hunter hit rate
    hunter_hit_rate = (len(enriched_list) / max(len(targetable), 1)) * 100

    # Top issues across all targetable (each can have multiple issues)
    from collections import Counter
    issue_counter: Counter[str] = Counter()
    cat_counter: Counter[str] = Counter()
    confidences: list[int] = []
    for p in targetable:
        for issue in (p.get("website_issues") or []):
            # Strip "bad-website:" prefix if present
            key = issue.split(":", 1)[-1] if ":" in issue else issue
            issue_counter[key] += 1
        if p.get("category"):
            cat_counter[p["category"]] += 1

    for e in enriched_list:
        c = (e.get("contact") or {}).get("confidence")
        if isinstance(c, (int, float)):
            confidences.append(int(c))

    n_skipped = sum(1 for s in sequences if s.get("skipped"))
    n_reviewed = sum(1 for s in sequences if s.get("reviewed") and not s.get("skipped"))

    return {
        "run_id": run_id,
        "n_total": scan.get("_meta", {}).get("n_total", 0),
        "n_targetable": len(targetable),
        "n_enriched": len(enriched_list),
        "n_sequences": len(sequences),
        "n_skipped": n_skipped,
        "n_reviewed": n_reviewed,
        "hunter_hit_rate_pct": round(hunter_hit_rate, 1),
        "avg_hunter_confidence": round(sum(confidences) / max(len(confidences), 1)) if confidences else 0,
        "top_issues": issue_counter.most_common(5),
        "top_categories": cat_counter.most_common(5),
    }


class SuppressionAddRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    via: str = Field("manual", min_length=1, max_length=30,
                      description="How they got onto the list. 'click' = real opt-out, "
                                  "'manual' = operator added, 'reply-stop' = reply-based")


class SuppressionRemoveRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)


@router.get("/suppressions")
def get_suppression_list(_=Depends(verify_admin_api_key)) -> dict:
    """Return the full CAN-SPAM opt-out list, newest first."""
    try:
        from core.cold_outreach import list_suppressions
        items = list_suppressions()
    except Exception as e:
        return {"suppressions": [], "error": str(e)[:200]}
    return {"suppressions": items, "count": len(items)}


@router.post("/suppressions/add")
def add_suppression_endpoint(req: SuppressionAddRequest,
                              _=Depends(verify_admin_api_key)) -> dict:
    """Manually add an email to the suppression list.

    Use cases:
      - Pre-suppress your own friends/family so they don't accidentally get scanned
      - Pre-suppress competitors you don't want to email
      - Handle off-channel opt-outs (reply STOP via text, phone request, etc.)
    """
    try:
        from core.cold_outreach import add_suppression
        add_suppression(req.email, via=req.via)
        log_event("suppression.added", email=req.email, via=req.via)
        return {"status": "ok", "email": req.email, "via": req.via}
    except Exception as e:
        raise HTTPException(500, f"Failed: {e!s}")


@router.post("/suppressions/remove")
def remove_suppression_endpoint(req: SuppressionRemoveRequest,
                                 _=Depends(verify_admin_api_key)) -> dict:
    """Re-include an email by removing it from the suppression list.

    Be VERY careful — only remove emails that were manually added by mistake.
    Removing a real opt-out (via='click') and then emailing them is a CAN-SPAM
    violation.
    """
    try:
        from core.cold_outreach import remove_suppression
        removed = remove_suppression(req.email)
        if removed:
            log_event("suppression.removed", email=req.email)
        return {"status": "ok", "email": req.email, "was_present": removed}
    except Exception as e:
        raise HTTPException(500, f"Failed: {e!s}")


@router.post("/instantly/auto-create-campaign")
def auto_create_campaign(_=Depends(verify_admin_api_key)) -> dict:
    """Create a SiteBoost-templated campaign in Instantly + activate it.

    No body needed — uses default name "SiteBoost Outbound (auto)". The new
    campaign UUID is stored in active_campaign.json on the volume, which
    send_sequences reads as a override for INSTANTLY_CAMPAIGN_ID env var.

    Net effect: one button click and the operator has a working SiteBoost
    campaign in Instantly + the system is already using it. No manual UI work,
    no env var copy-paste.
    """
    try:
        from core.siteboost_instantly import create_siteboost_campaign
        result = create_siteboost_campaign()
        log_event("instantly.campaign_created",
                  status=result.get("status"),
                  campaign_id=result.get("id", result.get("campaign_id", "")),
                  name=result.get("name", ""))
        return result
    except Exception as e:
        raise HTTPException(500, f"Failed: {e!s}")


@router.get("/instantly/active-campaign")
def get_active_campaign(_=Depends(verify_admin_api_key)) -> dict:
    """Return the campaign UUID that send_sequences will use right now.
    Includes file-override info + env var fallback so the operator can see
    where the value came from."""
    try:
        from core.siteboost_instantly import get_active_campaign_id, get_active_campaign_info
        active_id = get_active_campaign_id()
        info = get_active_campaign_info()
        env_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()
        source = "file" if info else ("env" if env_id else "none")
        return {
            "active_id": active_id,
            "source": source,
            "file_info": info,
            "env_id": env_id[:8] + "..." if env_id else "",
        }
    except Exception as e:
        return {"active_id": "", "source": "error", "error": str(e)}


class DigestSendRequest(BaseModel):
    recipient_email: str = Field(..., min_length=5, max_length=120)


@router.post("/digest/send-now")
def send_digest_now(req: DigestSendRequest, _=Depends(verify_admin_api_key)) -> dict:
    """Fire the daily digest email immediately to the given address.

    Use to preview what the morning summary would look like, OR to test changes
    to the digest copy. Real autonomous firing is wired into the scheduler at
    7:00 UTC each day (when a schedule with name='__digest__' is configured).
    """
    try:
        from core.siteboost_digest import send_digest_email
        result = send_digest_email(req.recipient_email)
        log_event("digest.sent", recipient=req.recipient_email,
                  status=result.get("status"),
                  resend_id=result.get("resend_id", ""))
        return result
    except Exception as e:
        raise HTTPException(500, f"Digest failed: {e!s}")


@router.get("/digest/preview")
def preview_digest(_=Depends(verify_admin_api_key)) -> dict:
    """Return the digest's underlying data WITHOUT sending an email.

    Lets the dashboard render a preview card showing what would be sent.
    """
    try:
        from core.siteboost_digest import build_digest_data
        return {"status": "ok", "data": build_digest_data()}
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


@router.get("/launch-readiness")
def launch_readiness(_=Depends(verify_admin_api_key)) -> dict:
    """Comprehensive ready-to-send health check across 6 axes.

    Each axis returns {status: ok|warn|fail, label, detail, action}. The operator
    looks at this card before triggering /send and instantly knows what's safe
    to do. Status semantics:
        ok    — green check, no concerns
        warn  — yellow, can ship but mildly risky
        fail  — red, hard stop, will produce bad sends

    This is the ONE endpoint to consult before any real outbound. Whole dashboard
    overview = this + recent runs.
    """
    import socket
    out: list[dict] = []

    # 1. CAN-SPAM physical address
    addr = os.getenv("SITEBOOST_PHYSICAL_ADDRESS", "")
    if not addr or "Placeholder" in addr:
        out.append({"axis": "can-spam", "status": "fail",
                    "label": "CAN-SPAM physical address",
                    "detail": "Address not set OR still 'Placeholder' fallback — sending mail with a fake address = federal CAN-SPAM violation ($46K/email max penalty)",
                    "action": "Set SITEBOOST_PHYSICAL_ADDRESS on Railway"})
    else:
        out.append({"axis": "can-spam", "status": "ok",
                    "label": "CAN-SPAM physical address",
                    "detail": addr[:80] + ("..." if len(addr) > 80 else ""),
                    "action": ""})

    # 2. Unsubscribe secret
    if not os.getenv("SITEBOOST_UNSUBSCRIBE_SECRET", "").strip():
        out.append({"axis": "unsubscribe", "status": "fail",
                    "label": "Unsubscribe token secret",
                    "detail": "SITEBOOST_UNSUBSCRIBE_SECRET not set — every /u/{token} click would 503",
                    "action": "Set the env var via railway variables --set"})
    else:
        out.append({"axis": "unsubscribe", "status": "ok",
                    "label": "Unsubscribe token system",
                    "detail": "Secret set, /u/{token} endpoint live, suppression list volume-mounted",
                    "action": ""})

    # 3. Sending domain auth (DNS)
    domain = os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com")
    dns_status = "ok"
    dns_detail_parts: list[str] = []
    try:
        # Quick check: just verify the domain resolves (basic DNS reachable)
        socket.gethostbyname(domain)
        dns_detail_parts.append(f"{domain} resolves")
    except Exception as e:
        dns_status = "warn"
        dns_detail_parts.append(f"{domain} DNS lookup failed ({type(e).__name__})")
    out.append({"axis": "dns", "status": dns_status,
                "label": "Outbound domain DNS",
                "detail": "; ".join(dns_detail_parts) +
                          " — SPF/DKIM/DMARC are NOT validated from inside the container (no dig). Verify externally with dig + mail-tester.com.",
                "action": "" if dns_status == "ok" else "Check Cloudflare DNS"})

    # 4. Instantly campaign
    if not os.getenv("INSTANTLY_API_KEY", "").strip():
        out.append({"axis": "instantly-key", "status": "fail",
                    "label": "Instantly API key",
                    "detail": "INSTANTLY_API_KEY not set — POST /send will return 'blocked'",
                    "action": "Rotate key in Instantly dashboard, set via Railway env"})
    elif not os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip():
        out.append({"axis": "instantly-campaign", "status": "fail",
                    "label": "Instantly campaign ID",
                    "detail": "INSTANTLY_CAMPAIGN_ID not set — POST /send will return 'blocked'",
                    "action": "Pick a campaign in Instantly UI, set INSTANTLY_CAMPAIGN_ID env"})
    else:
        out.append({"axis": "instantly", "status": "ok",
                    "label": "Instantly API + campaign",
                    "detail": "Key set; campaign UUID set. Send pipeline can POST leads.",
                    "action": ""})

    # 5. Suppression list health
    try:
        from core.cold_outreach import list_suppressions
        supps = list_suppressions()
        n = len(supps)
        clicks = sum(1 for s in supps if s.get("via") == "click")
        out.append({"axis": "suppression", "status": "ok" if n >= 0 else "warn",
                    "label": "Suppression list",
                    "detail": f"{n} total ({clicks} from real opt-out clicks). Volume-backed at SITEBOOST_SUPPRESSIONS_PATH.",
                    "action": ""})
    except Exception as e:
        out.append({"axis": "suppression", "status": "warn",
                    "label": "Suppression list",
                    "detail": f"Check failed: {e}",
                    "action": "Verify SITEBOOST_SUPPRESSIONS_PATH"})

    # 6. Resend (transactional sender for test-send and test-all)
    if not os.getenv("RESEND_API_KEY", "").strip():
        out.append({"axis": "resend", "status": "warn",
                    "label": "Resend test-send",
                    "detail": "RESEND_API_KEY not set — /send-test and /send-test-all will 503. Real outbound via Instantly is independent.",
                    "action": "Set RESEND_API_KEY on Railway"})
    else:
        out.append({"axis": "resend", "status": "ok",
                    "label": "Resend test-send",
                    "detail": "Key set, /send-test endpoint will dispatch via Resend.",
                    "action": ""})

    # Overall verdict
    n_fail = sum(1 for x in out if x["status"] == "fail")
    n_warn = sum(1 for x in out if x["status"] == "warn")
    verdict = "ok" if n_fail == 0 and n_warn == 0 else ("fail" if n_fail > 0 else "warn")

    return {"verdict": verdict, "checks": out, "n_fail": n_fail, "n_warn": n_warn}


@router.get("/events")
def list_events(limit: int = 100, _=Depends(verify_admin_api_key)) -> dict:
    """Activity log — recent operator + system events, newest first.

    Capped at 500 (Pydantic-validated). Use to see what's been happening:
    scans started, sequences skipped/reviewed/edited, test sends, real dispatches,
    unsubscribe clicks.
    """
    limit = max(1, min(limit, 500))
    return {"events": get_recent_events(limit), "limit": limit}


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
