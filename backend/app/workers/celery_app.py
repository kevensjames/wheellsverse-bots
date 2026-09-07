from celery import Celery
from celery.schedules import crontab

from app.config import settings


celery_app = Celery(
    "wheellsverse",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks", "app.workers.holding_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

celery_app.conf.beat_schedule = {
    "ingest-market-data": {
        "task": "app.workers.tasks.ingest_all_assets",
        "schedule": crontab(minute=f"*/{settings.MARKET_DATA_FETCH_INTERVAL_MINUTES}"),
    },
    "predict-stocks": {
        "task": "app.workers.tasks.predict_all_stocks",
        "schedule": crontab(minute=f"*/{settings.STOCK_PREDICTION_INTERVAL_MINUTES}"),
    },
    "predict-crypto": {
        "task": "app.workers.tasks.predict_all_crypto",
        "schedule": crontab(minute=f"*/{settings.CRYPTO_PREDICTION_INTERVAL_MINUTES}"),
    },
}

# Holding morning briefing — scheduled ONLY when enabled (default off → not scheduled).
# Report-only; ~07:00 America/New_York via the configurable UTC hour (DST-adjustable).
if getattr(settings, "KAI_HOLDING_BRIEFING_ENABLED", False):
    celery_app.conf.beat_schedule["holding-morning-briefing"] = {
        "task": "app.workers.holding_tasks.morning_briefing",
        "schedule": crontab(hour=int(getattr(settings, "KAI_HOLDING_BRIEFING_UTC_HOUR", 11)), minute=0),
    }

# §30 Holding autonomous cycle — bounded, on the EXISTING scheduler. DARK by default: the entry is added
# ONLY when the dedicated KAI_HOLDING_CYCLE_ENABLED is on (else {} → not scheduled; decoupled from watch),
# and even then the tick reuses build_live_engine, whose 3 fail-closed brakes (all off by default) execute
# 0 — a no-change cycle yields 0 work. Deploy-not-enable: scheduling this grants NO authority. No new daemon (§79).
from app.services.holding.holding_cycle import beat_schedule_entry as _holding_cycle_beat  # noqa: E402
celery_app.conf.beat_schedule.update(_holding_cycle_beat(settings))
