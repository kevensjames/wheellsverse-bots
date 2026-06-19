"""Real-time collaboration WebSocket — shared rooms with presence + broadcast.

  WS /ws/collab/{room}?token=<ADMIN_TOKEN>&name=<display name>

Clients receive {"type":"presence","users":[...]} on join/leave and
{"type":"message","from":..,"text":..} for every message any member sends.
Auth: token query param must equal settings.admin_token (WS can't use the
X-Admin-Token header from browsers). The hub logic lives in services/collab.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.services.collab import hub

router = APIRouter()


@router.websocket("/ws/collab/{room}")
async def collab_ws(ws: WebSocket, room: str):
    token = ws.query_params.get("token")
    expected = settings.admin_token
    if not expected or token != expected:
        await ws.close(code=1008)  # policy violation
        return
    name = (ws.query_params.get("name") or "guest")[:40]
    await ws.accept()
    cid = uuid.uuid4().hex
    hub.join(room, cid, ws, {"name": name})
    await hub.broadcast(room, {"type": "presence", "users": hub.presence(room)})
    try:
        while True:
            data = await ws.receive_json()
            kind = (data or {}).get("type", "message")
            if kind == "message":
                await hub.broadcast(room, {
                    "type": "message", "from": name, "text": str(data.get("text", ""))[:4000],
                })
            elif kind == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(room, cid)
        await hub.broadcast(room, {"type": "presence", "users": hub.presence(room)})
