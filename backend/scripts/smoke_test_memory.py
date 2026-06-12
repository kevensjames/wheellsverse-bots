"""Memory layer smoke test.

Usage:
    cd backend
    DATABASE_URL=<supabase-direct-or-pooler> OPENAI_API_KEY=... \
        python -m scripts.smoke_test_memory
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# Make `app.*` importable when invoked as a script
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.memory.retrieval import search_memories
from app.services.memory.store import add_memories_bulk, count_memories


def main() -> None:
    url = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DIRECT_DATABASE_URL or DATABASE_URL")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY")

    engine = create_engine(url, future=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = SessionLocal()

    uid = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO profiles (id, email, tier) "
            "VALUES (:id, :email, 'free')"
        ),
        {"id": str(uid), "email": f"smoke-{uid}@example.com"},
    )

    fixtures = [
        ("User is building WheellsVerse, an AI ecosystem", "fact"),
        ("User lives in Taunton, MA", "fact"),
        ("Prefers direct, no-fluff communication", "preference"),
        ("Has a Mac mini running 24/7 for AI services", "fact"),
        ("Working on the NAI companion AI MVP today", "event"),
    ]
    add_memories_bulk(db, user_id=uid, items=fixtures)
    db.commit()
    print(f"Inserted {count_memories(db, uid)} memories.\n")

    queries = [
        "where does the user live",
        "what is the user building",
        "how does the user like to communicate",
    ]
    for q in queries:
        print(f"Q: {q}")
        results = search_memories(db, user_id=uid, query=q, k=3)
        for r in results:
            print(
                f"  score={r.score:.3f}  sim={r.similarity:.3f}  "
                f"rec={r.recency:.3f}  [{r.memory_type}]  {r.content}"
            )
        print()

    db.execute(text("DELETE FROM memories WHERE user_id = :uid"), {"uid": str(uid)})
    db.execute(text("DELETE FROM profiles WHERE id = :uid"), {"uid": str(uid)})
    db.commit()
    db.close()
    print("Smoke test complete. Cleanup done.")


if __name__ == "__main__":
    main()
