"""Daily check-in — KAI proactively reaches out once a day.

composer.py   — build the warm message from real context (twin/eq/relationship).
storage.py    — one check-in per day (unique date_key).
scheduler.py  — daemon thread that sends it via Telegram at a UTC hour.

Scope KAI_SCOPE_CHECKIN; opt-in via KAI_CHECKIN_SCHEDULER_ENABLED.
"""
from app.services.checkin import composer, scheduler, storage

__all__ = ["composer", "scheduler", "storage"]
