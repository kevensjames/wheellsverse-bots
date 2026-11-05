"""
Briefing route — preview and on-demand delivery.

  POST /api/v2/narai/briefing/preview  — returns the assembled text JSON
  POST /api/v2/narai/briefing/markdown — the same, without HTML tags
  POST /api/v2/narai/briefing/now      — assembles AND delivers via Telegram
  POST /api/v2/narai/briefing/test     — fires the daily cron's callback

Every POST requires a NarAI token (require_auth, each route's direct
dependency). The two lines the briefing reads from the daily numbers board,
yesterday's revenue and the KPI line, are the owner's numbers: a route puts
them in only when the request also passes the app's owner check (owner_check:
the X-API-Key header or an owner wv_session cookie, as core.api decides it),
and leaves them out otherwise (assemble_briefing(board=False)); the rest of
the briefing is the same for every NarAI token. The briefing is built in a
worker thread: its sections read the board's database and call Google,
Telegram and Discord, which must never hold the event loop. The
cron-scheduled daily fire bypasses HTTP entirely (see
narai.integrations.scheduler) and keeps the board's lines.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from narai.api.auth import require_auth
from narai.integrations.briefing import (
    assemble_briefing,
    assemble_briefing_markdown,
    deliver_via_telegram,
)

rt = APIRouter(tags=["briefing"])
logger = logging.getLogger("narai.briefing.route")


def owner_check(request: Request) -> bool:
    """Whether this request also passes the app's owner check: the X-API-Key
    header equal to API_KEY, or an owner session cookie (with the CSRF origin
    check on these POSTs), as core/api.py's verify_api_key decides it
    (core.api.owner_request_ok); with API_KEY unset, only a declared local
    environment passes. It refuses nothing: it decides whether the board's
    lines go in, and anything that goes wrong leaves them out. Imported at
    call time: core.api mounts this router, and importing it here at load
    time would be circular."""
    try:
        from core.api import owner_request_ok
        return bool(owner_request_ok(request))
    except Exception as e:  # noqa: BLE001 — fail closed: no board lines
        logger.warning(f"briefing owner check unavailable ({type(e).__name__}): board lines left out")
        return False


@rt.post("/briefing/preview")
async def briefing_preview(_=Depends(require_auth), owner: bool = Depends(owner_check)) -> dict:
    """Build the briefing and return it without sending. Useful for the
    dashboard to render a 'preview today's briefing' panel. The board's
    lines only for the app's owner."""
    text = await asyncio.to_thread(assemble_briefing, board=owner)
    return {"text": text, "delivered": False}


@rt.post("/briefing/markdown")
async def briefing_markdown(_=Depends(require_auth), owner: bool = Depends(owner_check)) -> dict:
    """Same content as /briefing/preview but stripped of HTML tags so it
    can be dropped into Slack, email, SMS, or any non-Telegram channel."""
    text = await asyncio.to_thread(assemble_briefing_markdown, board=owner)
    return {"text": text, "format": "plain"}


@rt.post("/briefing/now")
async def briefing_now(_=Depends(require_auth), owner: bool = Depends(owner_check)) -> dict:
    """Build AND deliver the briefing on demand. Returns the assembled
    text plus a delivered:bool so the caller knows whether Telegram was
    actually pinged (returns False when TELEGRAM_BOT_TOKEN is unset).
    The text sent is the text returned: the board's lines only for the
    app's owner."""
    text = await asyncio.to_thread(assemble_briefing, board=owner)
    delivered = await deliver_via_telegram(text)
    return {"text": text, "delivered": delivered}


@rt.post("/briefing/test")
async def briefing_test(_=Depends(require_auth), owner: bool = Depends(owner_check)) -> dict:
    """Fire the same callback the daily 7am cron runs. Use this to verify
    Telegram setup before the cron actually fires — exercises the exact
    code path the scheduler will, not a parallel one. The briefing it sends
    has the board's lines only when the caller is the app's owner."""
    from narai.integrations.scheduler import _fire_briefing
    await _fire_briefing(board=owner)
    return {"status": "fired", "note": "check logs + Telegram for delivery confirmation"}


_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NarAI · Briefing</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'SF Pro',sans-serif;
         background: radial-gradient(circle at 30% 0%, #1a0033 0%, #0a001a 70%, #000 100%);
         color:#eaeaff; min-height:100vh; padding:32px 16px; }
  .card { max-width:520px; margin:24px auto; padding:24px 28px;
          background:rgba(20,10,40,0.6); border:1px solid rgba(136,68,255,0.3);
          border-radius:14px; backdrop-filter:blur(8px); }
  h1 { font-size:14px; letter-spacing:3px; text-transform:uppercase;
       color:#cc88ff; margin:0 0 16px 0; opacity:0.85; }
  pre { white-space:pre-wrap; word-break:break-word; line-height:1.6;
        font-family:-apple-system,BlinkMacSystemFont,sans-serif;
        font-size:14px; margin:0; color:#eaeaff; }
  pre.err { color:#ff6677; }
  .row { display:flex; gap:8px; margin-top:18px; }
  button { background:rgba(136,68,255,0.2); color:#cc88ff;
           border:1px solid rgba(136,68,255,0.5); border-radius:8px;
           padding:8px 14px; font-size:12px; cursor:pointer;
           font-family:inherit; font-weight:600; letter-spacing:0.5px; }
  button:hover { background:rgba(136,68,255,0.35); color:#fff; }
  .meta { font-size:11px; opacity:0.5; margin-top:10px; }
  .meta.err { color:#ff6677; opacity:1; }
</style>
</head>
<body>
<div class="card">
  <h1>📋 Today's Briefing</h1>
  <pre id="content">Loading…</pre>
  <div class="row">
    <button onclick="load()">↻ Refresh</button>
    <button onclick="fire()">⚡ Send to Telegram</button>
  </div>
  <div class="meta" id="meta"></div>
</div>
<script>
const T = localStorage.getItem('narai_v2_token') || '';
const C = document.getElementById('content');
const M = document.getElementById('meta');

function setError(el, msg) {
  el.classList.add('err');
  el.textContent = msg;
}
function clearError(el) { el.classList.remove('err'); }

async function load() {
  if (!T) { setError(C, 'Not logged in. Open /admin and click v2, then come back.'); return; }
  clearError(C); C.textContent = 'Loading…';
  try {
    const r = await fetch('/api/v2/narai/briefing/markdown', {
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+T},
    });
    if (r.status === 401) {
      localStorage.removeItem('narai_v2_token');
      setError(C, 'Session expired. Open /admin to re-login.');
      return;
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    C.textContent = d.text || '(empty briefing)';
    clearError(M); M.textContent = 'Fetched at ' + new Date().toLocaleTimeString();
  } catch (e) {
    setError(C, 'Error: ' + e.message);
  }
}

// The server's reason for a refusal: FastAPI's {detail} or an {error}, else the status.
function reason(d, status) {
  if (d && typeof d.detail === 'string' && d.detail) return d.detail;
  if (d && typeof d.error === 'string' && d.error) return d.error;
  return 'HTTP ' + status;
}

async function fire() {
  if (!T) return;
  clearError(M); M.textContent = 'Firing…';
  try {
    const r = await fetch('/api/v2/narai/briefing/test', {
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+T},
    });
    const d = await r.json().catch(() => null);
    if (!r.ok) {                       // 401, 403, 503…: nothing was sent
      setError(M, 'Not sent: ' + reason(d, r.status));   // textContent: shown as text, never HTML
      return;
    }
    M.textContent = 'Fired at ' + new Date().toLocaleTimeString() +
                    ' — ' + ((d && (d.note || d.status)) || 'ok');
  } catch (e) {
    setError(M, 'Fire failed: ' + e.message);
  }
}

load();
</script>
</body>
</html>
"""


@rt.get("/briefing", response_class=HTMLResponse)
async def briefing_page() -> HTMLResponse:
    """Standalone page that fetches /briefing/markdown using the JWT in
    localStorage. Pattern matches the voice avatar (page loads unauth,
    JS-fetched content is auth-gated). Bookmark-friendly URL:
    https://app.wheellsverse.com/api/v2/narai/briefing"""
    return HTMLResponse(_PAGE_HTML)
