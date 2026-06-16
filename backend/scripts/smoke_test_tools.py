"""End-to-end smoke test — exercises tools + memory + spend tracking.

Run:
    cd backend
    DATABASE_URL=<supabase-url> \
        OPENAI_API_KEY=... ANTHROPIC_API_KEY=... PERPLEXITY_API_KEY=... \
        python -m scripts.smoke_test_tools

Expected cost: ~$0.02 total. Expected runtime: ~30s.
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
from app.services.tools import ToolContext, build_default_registry


def main() -> None:
    url = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DIRECT_DATABASE_URL or DATABASE_URL")

    have_perplexity = bool(os.environ.get("PERPLEXITY_API_KEY"))
    if not have_perplexity:
        print("WARN: PERPLEXITY_API_KEY missing — web_search tool will be skipped")

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
    registry = build_default_registry(include_perplexity=have_perplexity)
    ctx = ToolContext(user_id=uid, session=db)

    prompts: list[tuple[str, str]] = [
        (
            "memory_save",
            "Please remember that my favorite stock is NVDA. "
            "I focus on chip-related companies.",
        ),
        (
            "memory_recall",
            "What did I tell you my favorite stock was?",
        ),
        (
            "trading_signal",
            "Run a technical analysis on AAPL for me.",
        ),
    ]
    if have_perplexity:
        prompts.append(
            ("web_search", "What was the closing price of Bitcoin yesterday?")
        )

    system = (
        "You are NAI, a personal AI for the user. Tools available: "
        "memory_tool (save/search user memories), "
        "trading_signal (TA on a ticker), "
        + ("web_search (live web). " if have_perplexity else "")
        + "When a tool is appropriate, call it. Otherwise answer directly."
    )

    for label, prompt in prompts:
        print(f"\n--- [{label}] {prompt}")
        try:
            result = router.chat(
                user_id=uid,
                messages=[{"role": "user", "content": prompt}],
                tool_registry=registry,
                tool_context=ctx,
                system=system,
                max_tokens=400,
                max_tool_iters=5,
            )
            print(f"  adapter={result.adapter} cost=${result.cost_usd:.6f}")
            print(f"  content: {result.content[:400]}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("\n--- llm_call_log audit (most recent 10 rows):")
    rows = db.execute(
        text(
            "SELECT adapter, model, input_tokens, output_tokens, "
            "cost_usd, latency_ms, success FROM llm_call_log "
            "WHERE user_id = :uid ORDER BY created_at DESC LIMIT 10"
        ),
        {"uid": str(uid)},
    ).all()
    for r in rows:
        latency_disp = f"{r.latency_ms or '-':>5}"
        print(
            f"  {r.adapter:10} {r.model:30} "
            f"in={r.input_tokens:5} out={r.output_tokens:5} "
            f"${r.cost_usd:.6f} {latency_disp}ms ok={r.success}"
        )

    mem_count = db.execute(
        text("SELECT COUNT(*) AS c FROM memories WHERE user_id = :uid"),
        {"uid": str(uid)},
    ).first()
    print(f"\nMemories saved during smoke: {mem_count.c}")

    db.execute(text("DELETE FROM memories WHERE user_id = :uid"), {"uid": str(uid)})
    db.execute(text("DELETE FROM llm_call_log WHERE user_id = :uid"), {"uid": str(uid)})
    db.execute(text("DELETE FROM profiles WHERE id = :uid"), {"uid": str(uid)})
    db.commit()
    db.close()
    print("\nSmoke complete. Test data cleaned up.")


if __name__ == "__main__":
    main()
