# KAI Real-Time Collaboration (Rooms)

Shared rooms where multiple people see each other's **presence** and a live
**broadcast** message feed in real time.

## Backend (done + tested)
- `services/collab/hub.py` — `Hub`: rooms → connections, `join/leave/presence/
  count/broadcast` (pure logic, 4 unit tests in `tests/test_collab_hub.py`).
- `routers/ws_collab.py` — `WS /ws/collab/{room}?token=<ADMIN_TOKEN>&name=<name>`.
  - On join/leave every member gets `{"type":"presence","users":[{name,id}]}`.
  - Sending `{"type":"message","text":"..."}` broadcasts
    `{"type":"message","from":<name>,"text":...}` to the whole room.
  - `{"type":"ping"}` → `{"type":"pong"}`.
  - Auth: `token` query param must equal `settings.admin_token` (browsers can't
    set the X-Admin-Token header on a WebSocket).

## Connect (quick test)
```js
const ws = new WebSocket(`wss://<host>/ws/collab/main?token=<ADMIN_TOKEN>&name=Jhon`);
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.onopen = () => ws.send(JSON.stringify({ type: "message", text: "hello room" }));
```

## Remaining (needs the live daemon + 2 clients to verify)
- **UI:** a "Room" presence bar + shared feed on the dashboard (or fold KAI chat
  replies into a room broadcast so collaborators watch KAI answer live).
- **Broadcast KAI replies:** have `/admin/kai-chat` publish each reply to the
  caller's room so everyone sees KAI's answers in real time.
- **Scale note:** the hub is in-memory per-process — fine for one daemon; a
  multi-process deploy would need a Redis/pub-sub fan-out.

## Tests
`cd backend && ../.venv/bin/python -m pytest tests/test_collab_hub.py -q --noconftest`
