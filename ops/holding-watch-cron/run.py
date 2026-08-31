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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
