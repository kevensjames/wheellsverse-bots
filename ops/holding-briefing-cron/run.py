"""Daily holding morning-briefing cron runner (Railway cron service).

Runs the report-only briefing ONCE with persist=True, so a KPI snapshot is stored each day and
the on-demand briefing's movement shows real day-over-day deltas. Report-only: NEVER sends
externally (delivery to any recipient is a separate approval-gated action). Flag-gated by
KAI_HOLDING_BRIEFING_ENABLED (the task itself no-ops when off). Matches the observability-monitor
pattern: a lightweight scheduled job, not a long-running Celery worker/beat.

Deployed as a second service in kai-production (shares the same Postgres, so persisted history is
visible to kai-prod's /admin/holding/briefing endpoint). See DEPLOY_CRON.md.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))


def main() -> int:
    from app.workers.holding_tasks import morning_briefing   # flag-gated, persist=True, audited
    result = morning_briefing()
    print("holding-briefing-cron:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
