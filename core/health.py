#!/usr/bin/env python3
"""
core/health.py
─────────────────────────────────────────────────────────────────────────────
Bot Health Registry — tracks status, run history, and error rates per bot.
Persists to JSON so data survives restarts.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
HEALTH_FILE = ROOT / "data" / "bot_health.json"

logger = logging.getLogger("health")


class BotHealthRecord:
    """Per-bot health tracking."""

    MAX_HISTORY = 50  # keep last 50 runs per bot

    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.status: str = "idle"          # idle | running | ok | failed | timeout
        self.last_run: Optional[str] = None
        self.last_success: Optional[str] = None
        self.last_failure: Optional[str] = None
        self.run_count: int = 0
        self.success_count: int = 0
        self.failure_count: int = 0
        self.total_duration: float = 0.0
        self.last_duration: float = 0.0
        self.last_error: Optional[str] = None
        self.history: deque = deque(maxlen=self.MAX_HISTORY)
        self.consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        if self.run_count == 0:
            return 1.0
        return self.success_count / self.run_count

    @property
    def avg_duration(self) -> float:
        if self.run_count == 0:
            return 0.0
        return self.total_duration / self.run_count

    @property
    def health_score(self) -> int:
        """0-100 health score."""
        if self.run_count == 0:
            return 100
        score = int(self.success_rate * 100)
        # Penalise consecutive failures
        score -= self.consecutive_failures * 10
        return max(0, min(100, score))

    def record_start(self):
        self.status = "running"
        self.run_count += 1
        self.last_run = datetime.now().isoformat()

    def record_success(self, duration: float):
        self.status = "ok"
        self.last_success = datetime.now().isoformat()
        self.success_count += 1
        self.last_duration = duration
        self.total_duration += duration
        self.consecutive_failures = 0
        self.last_error = None
        self.history.append({
            "ts": self.last_run,
            "status": "success",
            "duration": round(duration, 2),
        })

    def record_failure(self, duration: float, error: str):
        self.status = "failed"
        self.last_failure = datetime.now().isoformat()
        self.failure_count += 1
        self.last_duration = duration
        self.total_duration += duration
        self.consecutive_failures += 1
        self.last_error = str(error)[:500]
        self.history.append({
            "ts": self.last_run,
            "status": "failure",
            "duration": round(duration, 2),
            "error": self.last_error,
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "health_score": self.health_score,
            "success_rate": round(self.success_rate, 3),
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "avg_duration": round(self.avg_duration, 2),
            "last_duration": round(self.last_duration, 2),
            "last_run": self.last_run,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_error": self.last_error,
            "history": list(self.history)[-10:],  # last 10 for API
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BotHealthRecord":
        r = cls(d["name"], d.get("category", ""))
        r.status = d.get("status", "idle")
        r.last_run = d.get("last_run")
        r.last_success = d.get("last_success")
        r.last_failure = d.get("last_failure")
        r.run_count = d.get("run_count", 0)
        r.success_count = d.get("success_count", 0)
        r.failure_count = d.get("failure_count", 0)
        r.consecutive_failures = d.get("consecutive_failures", 0)
        r.total_duration = d.get("avg_duration", 0) * d.get("run_count", 0)
        r.last_duration = d.get("last_duration", 0)
        r.last_error = d.get("last_error")
        hist = d.get("history", [])
        r.history = deque(hist, maxlen=cls.MAX_HISTORY)
        return r


class HealthRegistry:
    """Central registry for all bot health records."""

    def __init__(self):
        self._records: Dict[str, BotHealthRecord] = {}
        self._lock = threading.Lock()
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        if HEALTH_FILE.exists():
            try:
                data = json.loads(HEALTH_FILE.read_text())
                for full_name, d in data.items():
                    self._records[full_name] = BotHealthRecord.from_dict(d)
                logger.info(f"Health registry loaded ({len(self._records)} records)")
            except Exception as e:
                logger.warning(f"Could not load health file: {e}")

    def save(self):
        try:
            data = {k: v.to_dict() for k, v in self._records.items()}
            HEALTH_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Could not save health file: {e}")

    # ─── Record management ────────────────────────────────────────────────────

    def get_or_create(self, full_name: str, category: str = "") -> BotHealthRecord:
        with self._lock:
            if full_name not in self._records:
                name = full_name.split("/")[-1]
                self._records[full_name] = BotHealthRecord(name, category)
            return self._records[full_name]

    def record_start(self, full_name: str, category: str = ""):
        rec = self.get_or_create(full_name, category)
        rec.record_start()

    def record_success(self, full_name: str, duration: float):
        if full_name in self._records:
            self._records[full_name].record_success(duration)
            self.save()

    def record_failure(self, full_name: str, duration: float, error: str):
        if full_name in self._records:
            self._records[full_name].record_failure(duration, error)
            self.save()

    # ─── Queries ──────────────────────────────────────────────────────────────

    def get_all(self) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._records.values()]

    def get_failed_bots(self) -> List[str]:
        with self._lock:
            return [k for k, v in self._records.items() if v.status == "failed"]

    def get_unhealthy_bots(self, threshold: int = 70) -> List[str]:
        with self._lock:
            return [k for k, v in self._records.items()
                    if v.run_count > 0 and v.health_score < threshold]

    def get_summary(self) -> Dict:
        with self._lock:
            records = list(self._records.values())
            total = len(records)
            ran = [r for r in records if r.run_count > 0]
            failed = [r for r in records if r.status == "failed"]
            healthy = [r for r in ran if r.health_score >= 80]
            avg_score = (sum(r.health_score for r in ran) / len(ran)) if ran else 100
            return {
                "total_tracked": total,
                "bots_ran": len(ran),
                "currently_failed": len(failed),
                "healthy": len(healthy),
                "avg_health_score": round(avg_score, 1),
                "failed_bots": [r.name for r in failed],
            }


# Singleton
_registry: Optional[HealthRegistry] = None


def get_health_registry() -> HealthRegistry:
    global _registry
    if _registry is None:
        _registry = HealthRegistry()
    return _registry
