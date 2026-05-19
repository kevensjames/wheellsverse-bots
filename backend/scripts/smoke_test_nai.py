"""End-to-end NAI smoke against a running uvicorn server.

Prereqs:
    uvicorn app.main:app --host 127.0.0.1 --port 8001
    export NAI_TEST_JWT="<token from POST /auth/login>"
    (optional) export NAI_BASE="http://127.0.0.1:8001"

Run:
    python -m scripts.smoke_test_nai
"""
from __future__ import annotations

import json
import os
import sys

import httpx


BASE = os.environ.get("NAI_BASE", "http://127.0.0.1:8001")
TOKEN = os.environ.get("NAI_TEST_JWT")


def _hdr() -> dict:
    if not TOKEN:
        sys.exit("Set NAI_TEST_JWT to a valid access token (POST /auth/login)")
    return {"Authorization": f"Bearer {TOKEN}"}


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60.0) as c:
        print("\n[1] POST /nai/chat (no tools)")
        r = c.post(
            "/nai/chat",
            json={"message": "Hello, who are you?"},
            headers=_hdr(),
        )
        r.raise_for_status()
        data = r.json()
        conv_id = data["conversation_id"]
        print(f"  conv_id={conv_id}")
        print(f"  cost=${data['total_cost_usd']}")
        print(f"  reply: {data['message']['content'][:200]}")

        print("\n[2] POST /nai/chat (use_tools=True) — save memory")
        r = c.post(
            "/nai/chat",
            json={
                "message": "Remember that I prefer Python over JavaScript.",
                "conversation_id": conv_id,
                "use_tools": True,
            },
            headers=_hdr(),
        )
        r.raise_for_status()
        print(f"  reply: {r.json()['message']['content'][:200]}")

        print("\n[3] POST /nai/chat (use_tools=True) — recall memory")
        r = c.post(
            "/nai/chat",
            json={
                "message": "What language do I prefer?",
                "conversation_id": conv_id,
                "use_tools": True,
            },
            headers=_hdr(),
        )
        r.raise_for_status()
        print(f"  reply: {r.json()['message']['content'][:200]}")

        print("\n[4] GET /nai/chat/stream")
        params = {
            "message": "In one sentence, what is a hash table?",
            "conversation_id": conv_id,
            "token": TOKEN,
        }
        with c.stream("GET", "/nai/chat/stream", params=params) as r:
            r.raise_for_status()
            collected = []
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[len("data: "):])
                if event["type"] == "delta":
                    collected.append(event["content"])
                elif event["type"] == "done":
                    break
            print(f"  streamed: {''.join(collected)[:200]}")

        print("\n[5] GET /nai/conversations")
        r = c.get("/nai/conversations", headers=_hdr())
        r.raise_for_status()
        for conv in r.json():
            print(
                f"  - {conv['id']} ({conv['message_count']} msgs) "
                f"— {conv['title']}"
            )

    print("\nSmoke complete.")


if __name__ == "__main__":
    main()
