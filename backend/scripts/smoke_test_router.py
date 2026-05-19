"""Manual smoke test — hits all 4 adapters with $-cents-of-cost prompts.

Run:
    cd backend
    DATABASE_URL=<supabase-url> \
        OPENAI_API_KEY=... ANTHROPIC_API_KEY=... PERPLEXITY_API_KEY=... \
        python -m scripts.smoke_test_router
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.router import build_default_router


def main() -> None:
    url = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DIRECT_DATABASE_URL or DATABASE_URL")

    engine = create_engine(url, future=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = SessionLocal()

    uid = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO profiles (id, email, tier) "
            "VALUES (:id, :email, 'free') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(uid), "email": f"smoke-{uid}@example.com"},
    )
    db.commit()

    router = build_default_router(db)

    prompts = [
        ("general", "In one sentence, what is a hash table?"),
        ("code", "Write a Python one-liner to reverse a string."),
        ("realtime", "What's the current weather in Boston today?"),
    ]

    for label, prompt in prompts:
        print(f"\n--- [{label}] {prompt}")
        try:
            result = router.complete(
                user_id=uid,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
            )
            print(f"  adapter={result.adapter} model={result.model}")
            print(
                f"  latency={result.latency_ms}ms "
                f"tokens={result.input_tokens}/{result.output_tokens} "
                f"cost=${result.cost_usd:.6f}"
            )
            print(f"  content: {result.content[:200]}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("\n--- [local-forced] prefer_local=True")
    try:
        result = router.complete(
            user_id=uid,
            messages=[{"role": "user", "content": "Say hi in 5 words."}],
            prefer_local=True,
            max_tokens=40,
        )
        print(
            f"  adapter={result.adapter} latency={result.latency_ms}ms "
            f"cost=${result.cost_usd}"
        )
        print(f"  content: {result.content[:120]}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

    db.commit()

    rows = db.execute(
        text(
            "SELECT adapter, model, input_tokens, output_tokens, "
            "cost_usd, latency_ms, success FROM llm_call_log "
            "WHERE user_id = :uid ORDER BY created_at"
        ),
        {"uid": str(uid)},
    ).all()
    print("\nllm_call_log rows for this run:")
    for r in rows:
        print(f"  {dict(r._mapping)}")

    db.execute(text("DELETE FROM llm_call_log WHERE user_id = :uid"), {"uid": str(uid)})
    db.execute(text("DELETE FROM profiles WHERE id = :uid"), {"uid": str(uid)})
    db.commit()
    db.close()
    print("\nSmoke test complete. Cleanup done.")


if __name__ == "__main__":
    main()
