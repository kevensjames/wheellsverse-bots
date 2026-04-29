from celery import Celery
from celery.schedules import crontab

from app.config import settings


celery_app = Celery(
    "wheellsverse",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
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
