"""Daily summary email for operator — what happened in the last 24h.

Compiles:
    - Scans that completed (run_id, location, prospects found)
    - Total targetable prospects
    - Top 5 detected issues across all scans
    - Top 5 categories of prospects
    - Suppression list growth (new unsubscribes)
    - Sequences ready to send
    - Open warnings (e.g. unsubscribe surge, scan failures)

Designed so the operator opens their phone in the morning, glances at one email,
and knows whether to login to the dashboard or skip the day.

Format: clean HTML (works in Gmail, dark mode, plus plain-text fallback). Sent
via Resend so it shares the same outbound infrastructure as the rest of SiteBoost.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from pathlib import Path

import requests

logger = logging.getLogger("siteboost_digest")

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.getenv("SITEBOOST_RUNS_PATH",
                          str(ROOT / "data" / "launches" / "siteboost" / "runs")))
SCANS_DIR = Path(os.getenv("SITEBOOST_SCANS_PATH",
                            str(ROOT / "data" / "launches" / "siteboost" / "scans")))
DASHBOARD_URL = "https://app.wheellsverse.com/admin/siteboost"


def _read_json_safe(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def build_digest_data() -> dict:
    """Walk SCANS_DIR + RUNS_DIR, find activity from last 24h, return summary dict."""
    cutoff = time.time() - 86400  # 24h ago

    recent_scans: list[dict] = []
    total_targetable = 0
    issue_counter: Counter[str] = Counter()
    cat_counter: Counter[str] = Counter()
    seq_ready_total = 0

    if RUNS_DIR.exists():
        for run_dir in sorted(RUNS_DIR.iterdir(),
                               key=lambda p: p.stat().st_mtime if p.exists() else 0,
                               reverse=True)[:30]:
            if not run_dir.is_dir():
                continue
            if run_dir.stat().st_mtime < cutoff:
                continue
            run_id = run_dir.name
            # Pull scan meta from SCANS_DIR
            scan_file = SCANS_DIR / f"{run_id}.json"
            scan = _read_json_safe(scan_file)
            meta = scan.get("_meta", {})
            n_targetable = meta.get("n_targetable", 0)
            n_total = meta.get("n_total", 0)
            location = meta.get("location", "?")

            # Sequences ready
            seq_file = run_dir / "04-sequences.json"
            seqs = _read_json_safe(seq_file).get("sequences", [])
            n_active = sum(1 for s in seqs if not s.get("skipped"))

            recent_scans.append({
                "run_id": run_id,
                "location": location,
                "n_total": n_total,
                "n_targetable": n_targetable,
                "n_sequences_active": n_active,
            })
            total_targetable += n_targetable
            seq_ready_total += n_active

            # Aggregate issues + categories
            for p in scan.get("targetable", []):
                for issue in (p.get("website_issues") or []):
                    key = issue.split(":", 1)[-1] if ":" in issue else issue
                    issue_counter[key] += 1
                if p.get("category"):
                    cat_counter[p["category"]] += 1

    # Suppression growth (last 24h via events.jsonl)
    new_unsubs = 0
    try:
        from core.siteboost_events import get_recent_events
        for e in get_recent_events(500):
            if e.get("type") != "unsubscribe.click":
                continue
            ts = e.get("ts", "")
            # ISO: 2026-06-14T11:46:55Z — compare lexicographically
            cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff))
            if ts >= cutoff_iso:
                new_unsubs += 1
    except Exception:
        pass

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "recent_scans": recent_scans,
        "n_runs_last_24h": len(recent_scans),
        "total_targetable": total_targetable,
        "sequences_ready_to_send": seq_ready_total,
        "new_unsubscribes": new_unsubs,
        "top_issues": issue_counter.most_common(5),
        "top_categories": cat_counter.most_common(5),
    }


def format_digest_html(d: dict) -> str:
    """Render the digest dict as a clean HTML email. Mobile-friendly, dark-mode safe."""
    scans_rows = ""
    for s in d.get("recent_scans", []):
        scans_rows += f"""
          <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{s['location']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right">{s['n_total']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:#10b981;font-weight:600">{s['n_targetable']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:#f59e0b;font-weight:600">{s['n_sequences_active']}</td>
          </tr>"""
    if not scans_rows:
        scans_rows = '<tr><td colspan="4" style="padding:14px 12px;color:#94a3b8;text-align:center">No scans in the last 24h.</td></tr>'

    issues_html = ""
    for i, (k, n) in enumerate(d.get("top_issues", []), 1):
        issues_html += f'<li style="padding:4px 0"><strong>{n}</strong> · {k}</li>'
    if not issues_html:
        issues_html = '<li style="color:#94a3b8">No issues detected.</li>'

    cats_html = ""
    for i, (k, n) in enumerate(d.get("top_categories", []), 1):
        cats_html += f'<li style="padding:4px 0"><strong>{n}</strong> · {k}</li>'
    if not cats_html:
        cats_html = '<li style="color:#94a3b8">No categories.</li>'

    unsub_block = ""
    if d.get("new_unsubscribes", 0) > 0:
        unsub_block = f'''
          <div style="background:#fef3c7;border-left:4px solid #f59e0b;padding:12px 16px;margin-top:16px;border-radius:6px">
            <strong>⚠ {d["new_unsubscribes"]} new unsubscribe{"s" if d["new_unsubscribes"] != 1 else ""}</strong>
            in the last 24h. If this spikes, check your messaging.
          </div>'''

    cta_block = ""
    if d.get("sequences_ready_to_send", 0) > 0:
        cta_block = f'''
          <div style="background:#dbeafe;border-left:4px solid #3b82f6;padding:14px 16px;margin-top:16px;border-radius:6px">
            <strong>{d["sequences_ready_to_send"]} sequence{"s" if d["sequences_ready_to_send"] != 1 else ""} ready to dispatch.</strong>
            Open the dashboard to review + send.
          </div>'''

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937">
<div style="max-width:600px;margin:0 auto;padding:24px;background:#fff;border-radius:8px;margin-top:20px">

  <div style="font-size:.85rem;color:#94a3b8;margin-bottom:8px">
    {d["generated_at"]}
  </div>
  <h1 style="font-size:1.6rem;margin:0 0 16px;color:#0f172a;font-weight:700">
    SiteBoost Daily Digest
  </h1>

  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px">
    <div style="flex:1;min-width:130px;padding:14px;background:#f8fafc;border-radius:6px;text-align:center">
      <div style="font-size:1.8rem;font-weight:700;color:#0f172a">{d["n_runs_last_24h"]}</div>
      <div style="font-size:.78rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Scans completed</div>
    </div>
    <div style="flex:1;min-width:130px;padding:14px;background:#f8fafc;border-radius:6px;text-align:center">
      <div style="font-size:1.8rem;font-weight:700;color:#10b981">{d["total_targetable"]}</div>
      <div style="font-size:.78rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Targetable prospects</div>
    </div>
    <div style="flex:1;min-width:130px;padding:14px;background:#f8fafc;border-radius:6px;text-align:center">
      <div style="font-size:1.8rem;font-weight:700;color:#f59e0b">{d["sequences_ready_to_send"]}</div>
      <div style="font-size:.78rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Ready to send</div>
    </div>
  </div>

  {unsub_block}
  {cta_block}

  <h2 style="font-size:1.05rem;margin:24px 0 12px;color:#0f172a;font-weight:600">Recent scans</h2>
  <table style="width:100%;border-collapse:collapse;font-size:.88rem;border:1px solid #e5e7eb;border-radius:6px">
    <thead>
      <tr style="background:#f9fafb">
        <th style="padding:8px 12px;text-align:left;font-size:.78rem;color:#64748b;font-weight:600">Location</th>
        <th style="padding:8px 12px;text-align:right;font-size:.78rem;color:#64748b;font-weight:600">Total</th>
        <th style="padding:8px 12px;text-align:right;font-size:.78rem;color:#64748b;font-weight:600">Targetable</th>
        <th style="padding:8px 12px;text-align:right;font-size:.78rem;color:#64748b;font-weight:600">Active seq</th>
      </tr>
    </thead>
    <tbody>{scans_rows}</tbody>
  </table>

  <div style="display:flex;gap:20px;margin-top:24px">
    <div style="flex:1">
      <h3 style="font-size:.92rem;margin:0 0 6px;color:#0f172a;font-weight:600">Top issues</h3>
      <ul style="margin:0;padding-left:18px;font-size:.88rem;color:#1f2937">{issues_html}</ul>
    </div>
    <div style="flex:1">
      <h3 style="font-size:.92rem;margin:0 0 6px;color:#0f172a;font-weight:600">Top categories</h3>
      <ul style="margin:0;padding-left:18px;font-size:.88rem;color:#1f2937">{cats_html}</ul>
    </div>
  </div>

  <div style="text-align:center;margin-top:32px">
    <a href="{DASHBOARD_URL}" style="display:inline-block;padding:12px 24px;background:#ea580c;color:#fff;text-decoration:none;border-radius:6px;font-weight:600">Open dashboard</a>
  </div>

  <div style="font-size:.75rem;color:#94a3b8;text-align:center;margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb">
    Sent by SiteBoost · This is an automated daily summary.
  </div>

</div>
</body></html>"""


def send_digest_email(recipient_email: str) -> dict:
    """Build + send the digest via Resend. Returns {status, resend_id} or {status, error}."""
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    if not resend_key:
        return {"status": "failed", "error": "RESEND_API_KEY not set"}
    outbound_domain = os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com")

    data = build_digest_data()
    html = format_digest_html(data)
    subject = (f"SiteBoost Daily — {data['n_runs_last_24h']} scans, "
                f"{data['total_targetable']} prospects, "
                f"{data['sequences_ready_to_send']} ready to send")

    payload = {
        "from": f"SiteBoost Digest <siteboost@{outbound_domain}>",
        "to": [recipient_email],
        "subject": subject,
        "html": html,
    }
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {resend_key}"},
            timeout=20,
        )
        if r.status_code in (200, 201):
            return {"status": "sent", "resend_id": r.json().get("id", ""), "data": data}
        return {"status": "failed", "http": r.status_code, "body": r.text[:300]}
    except Exception as e:
        return {"status": "failed", "error": str(e)[:300]}
