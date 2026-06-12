"""One-shot backfill: tag every row in narai_memory with user_id='owner'.

Run BEFORE the per-user filter ships in infra/brain/memory.py, so the admin
NarAI (which authenticates as sub='owner') keeps recalling its existing
memories after the where={'user_id': user_id} filter is added.

Idempotent: re-running is safe — rows already tagged keep their user_id.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import chromadb


DEFAULT_USER_ID = "owner"


def main() -> int:
    path = os.getenv("NARAI_CHROMA_PATH") or str(
        Path(__file__).resolve().parents[1] / "narai" / "data" / "chroma"
    )
    print(f"chroma path: {path}")

    client = chromadb.PersistentClient(path=path)
    try:
        col = client.get_collection("narai_memory")
    except Exception as e:
        print(f"narai_memory collection not found: {e}")
        return 0

    data = col.get(include=["metadatas"])
    ids = data["ids"]
    metas = data["metadatas"] or [None] * len(ids)
    if not ids:
        print("narai_memory has 0 rows — nothing to backfill")
        return 0

    new_metas = [{**(m or {}), "user_id": (m or {}).get("user_id") or DEFAULT_USER_ID}
                 for m in metas]
    col.update(ids=ids, metadatas=new_metas)
    print(f"backfilled user_id='{DEFAULT_USER_ID}' on {len(ids)} rows in narai_memory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
