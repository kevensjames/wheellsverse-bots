"""In-memory presence + broadcast hub for real-time collaboration rooms.

Pure logic — no FastAPI/WebSocket imports here, so it's unit-testable with a
fake connection (anything exposing `async send_json(obj)`). The WebSocket route
(routers/ws_collab.py) is the only thing that knows about real sockets.

A "connection" is any object with `async def send_json(self, obj) -> None`.
Each room maps client_id -> {"conn": conn, "meta": {...}}.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._rooms: dict[str, dict[str, dict[str, Any]]] = {}

    def join(self, room: str, client_id: str, conn: Any, meta: dict[str, Any] | None = None) -> None:
        self._rooms.setdefault(room, {})[client_id] = {"conn": conn, "meta": dict(meta or {})}

    def leave(self, room: str, client_id: str) -> None:
        r = self._rooms.get(room)
        if not r:
            return
        r.pop(client_id, None)
        if not r:
            self._rooms.pop(room, None)

    def presence(self, room: str) -> list[dict[str, Any]]:
        """The meta of everyone currently in the room (stable order by client_id)."""
        r = self._rooms.get(room, {})
        return [dict(v["meta"], id=cid) for cid, v in sorted(r.items())]

    def count(self, room: str) -> int:
        return len(self._rooms.get(room, {}))

    def rooms(self) -> list[str]:
        return sorted(self._rooms.keys())

    async def broadcast(self, room: str, message: dict[str, Any], *, exclude: str | None = None) -> int:
        """Send `message` to every connection in the room (except `exclude`).
        Dead connections (send raises) are dropped. Returns the number of
        successful sends."""
        r = self._rooms.get(room, {})
        sent = 0
        dead: list[str] = []
        for cid, entry in list(r.items()):
            if cid == exclude:
                continue
            try:
                await entry["conn"].send_json(message)
                sent += 1
            except Exception as e:  # pragma: no cover - defensive
                logger.info("collab: dropping dead connection %s: %s", cid, e)
                dead.append(cid)
        for cid in dead:
            self.leave(room, cid)
        return sent


# Process-wide singleton shared by the WebSocket route.
hub = Hub()
