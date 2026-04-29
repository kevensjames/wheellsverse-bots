"""Telegram webhook endpoint — receives Telegram POSTs, dispatches to handler."""
import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from narai.integrations.telegram import WEBHOOK_SECRET, handle_update

rt = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger("narai.telegram.route")

# Hold background task references so asyncio GC doesn't reap them mid-execution.
_BACKGROUND_TASKS: set = set()


@rt.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="invalid secret")

    update_data = await request.json()
    task = asyncio.create_task(handle_update(update_data))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return {"ok": True}
