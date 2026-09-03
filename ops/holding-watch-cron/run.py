"""Continuous holding-watch cron runner (Railway cron, every ~15 min).

Runs the read-only watch loop ONCE — senses current state, diffs against the last-seen state, and
sends a proactive alert to the operator's channel ONLY on material change — then exits. Flag-gated
(KAI_HOLDING_WATCH_ENABLED); alerts deliver only if KAI_HOLDING_DELIVERY_ENABLED + a channel is set.
Report-only; mutates nothing but its own watch-state row.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))


def main() -> int:
    from app.services.holding.watch import run_watch
    print("holding-watch-cron:", run_watch(deliver=True))
    # DETECT_ONLY self-improvement detection runs as part of the SAME bounded cycle (no new daemon, §3).
    # Read-only + flag-gated (KAI_SELF_IMPROVEMENT_DETECT_ENABLED); prepares nothing.
    try:
        from datetime import datetime, timezone
        from app.services.holding.self_improvement_detect import run_detection
        print("si-detect:", run_detection(now=datetime.now(timezone.utc).isoformat(), deliver=True))
    except Exception as e:
        print("si-detect: error", str(e)[:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
