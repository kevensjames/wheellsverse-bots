"""
Briefing route — preview and on-demand delivery.

  POST /api/v2/narai/briefing/preview  — returns the assembled text JSON
  POST /api/v2/narai/briefing/now      — assembles AND delivers via Telegram

Both endpoints require auth. The cron-scheduled daily fire bypasses HTTP
entirely (see narai.integrations.scheduler).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from narai.api.auth import require_auth
from narai.integrations.briefing import assemble_briefing, deliver_via_telegram

rt = APIRouter(tags=["briefing"])
logger = logging.getLogger("narai.briefing.route")


@rt.post("/briefing/preview")
async def briefing_preview(_=Depends(require_auth)) -> dict:
    """Build the briefing and return it without sending. Useful for the
    dashboard to render a 'preview today's briefing' panel."""
    text = assemble_briefing()
    return {"text": text, "delivered": False}


@rt.post("/briefing/now")
async def briefing_now(_=Depends(require_auth)) -> dict:
    """Build AND deliver the briefing on demand. Returns the assembled
    text plus a delivered:bool so the caller knows whether Telegram was
    actually pinged (returns False when TELEGRAM_BOT_TOKEN is unset)."""
    text = assemble_briefing()
    delivered = await deliver_via_telegram(text)
    return {"text": text, "delivered": delivered}


@rt.post("/briefing/test")
async def briefing_test(_=Depends(require_auth)) -> dict:
    """Fire the same callback the daily 7am cron runs. Use this to verify
    Telegram setup before the cron actually fires — exercises the exact
    code path the scheduler will, not a parallel one."""
    from narai.integrations.scheduler import _fire_briefing
    await _fire_briefing()
    return {"status": "fired", "note": "check logs + Telegram for delivery confirmation"}
