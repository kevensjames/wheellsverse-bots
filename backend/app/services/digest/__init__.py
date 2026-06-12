"""Operator Digest — proactive cross-subsystem synthesis pushed to Telegram.

  gather_snapshot() — compact state of audit/planning/learning/twin (defensive)
  build_digest()    — snapshot → LLM-synthesized digest text (fail-soft)
  send_digest()      — build + push to Telegram + log
  run_digest_cycle() — self-contained send for the scheduler thread
  list_digests()     — recent digest history
  scheduler          — opt-in daily auto-send (KAI_DIGEST_SCHEDULER_ENABLED)
"""
from app.services.digest.digest import (  # noqa: F401
    DIGEST_LOG_PATH,
    build_digest,
    gather_snapshot,
    list_digests,
    run_digest_cycle,
    send_digest,
)

__all__ = [
    "DIGEST_LOG_PATH",
    "build_digest",
    "gather_snapshot",
    "list_digests",
    "run_digest_cycle",
    "send_digest",
]
