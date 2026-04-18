"""Migrate existing NarAI data into the new Chroma + SQLite store.
Ports: data/narai_memory.json → ChromaDB narai_memory collection
       data/narai_activity.json → SQLite chat_logs (as import records)

Usage: python -m narai.scripts.migrate_legacy
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # wheellsverse_bots/
DATA = ROOT / "data"

# Ensure narai package is importable
sys.path.insert(0, str(ROOT))

from narai.core.db import ChatLog, MemoryEntry, SessionLocal, init_db
from narai.core.memory import remember


async def migrate_memory() -> int:
    path = DATA / "narai_memory.json"
    if not path.exists():
        print(f"  [skip] {path} not found")
        return 0

    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        print(f"  [skip] Unexpected format in narai_memory.json")
        return 0

    count = 0
    async with SessionLocal() as session:
        for e in entries:
            key = e.get("key", "")
            content = e.get("content", "")
            tags = e.get("tags", [])
            source = e.get("source", "legacy")

            if not key or not content:
                continue

            # Insert into ChromaDB
            chroma_id = remember(key, content, tags=tags, source=source)

            # Insert into SQLite for full-text history
            existing = await session.get(MemoryEntry, key)
            if existing is None:
                session.add(MemoryEntry(
                    key=key,
                    content=content,
                    tags=tags,
                    source=source,
                    chroma_id=chroma_id,
                ))
                count += 1

        await session.commit()

    print(f"  [memory] {count} entries migrated to Chroma + SQLite")
    return count


async def migrate_activity() -> int:
    path = DATA / "narai_activity.json"
    if not path.exists():
        print(f"  [skip] {path} not found")
        return 0

    raw = json.loads(path.read_text())

    # Activity log can be a list or dict with nested lists
    items = raw if isinstance(raw, list) else []
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list):
                items.extend(v)

    count = 0
    async with SessionLocal() as session:
        for item in items:
            if not isinstance(item, dict):
                continue
            msg = item.get("content") or item.get("message") or item.get("text") or ""
            if not msg:
                continue
            session.add(ChatLog(
                message="[LEGACY IMPORT]",
                response=msg,
                model_used="legacy",
                tier="fast",
                tokens_used=0,
                skill=item.get("category"),
            ))
            count += 1

        await session.commit()

    print(f"  [activity] {count} activity entries migrated to SQLite")
    return count


async def main() -> None:
    print("NarAI Legacy Migration")
    print("=" * 40)
    await init_db()
    m = await migrate_memory()
    a = await migrate_activity()
    print(f"\nDone. Total: {m + a} records migrated.")


if __name__ == "__main__":
    asyncio.run(main())
