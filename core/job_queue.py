#!/usr/bin/env python3
"""
core/job_queue.py
─────────────────────────────────────────────────────────────────────────────
Async job queue for bot execution.

Replaces the ThreadPoolExecutor pattern in api.py with a proper asyncio-based
queue that:
  - Accepts jobs from any endpoint (non-blocking)
  - Runs jobs concurrently up to MAX_WORKERS limit
  - Tracks status: pending → running → done / error
  - Persists job history (last 500 jobs in memory)
  - Emits log entries visible in the dashboard

Usage:
  from core.job_queue import get_queue, submit_job

  # Submit a bot run
  job_id = await submit_job(
      name="01_content_generator",
      fn=lambda: bot.execute(topic="AI investing"),
      meta={"bot": "01_content_generator", "topic": "AI investing"}
  )

  # Check status
  job = get_queue().get_job(job_id)
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Callable, Dict, Optional

logger = logging.getLogger("job_queue")

MAX_WORKERS = int(__import__("os").getenv("MAX_WORKERS", "6"))
MAX_HISTORY = 500


# ── Job model ─────────────────────────────────────────────────────────────────

class Job:
    __slots__ = (
        "id", "name", "meta", "status",
        "result", "error", "created_at", "started_at", "finished_at",
    )

    def __init__(self, job_id: str, name: str, meta: Dict):
        self.id = job_id
        self.name = name
        self.meta = meta
        self.status = "pending"   # pending | running | done | error
        self.result = None
        self.error = None
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "meta": self.meta,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": round((self.finished_at or time.time()) - (self.started_at or self.created_at), 2)
            if self.started_at else None,
        }


# ── Queue engine ──────────────────────────────────────────────────────────────

class JobQueue:
    """
    Asyncio-based bounded job queue.
    Safe to use from FastAPI's async context.
    """

    def __init__(self, max_workers: int = MAX_WORKERS):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: Dict[str, Job] = {}
        self._history: deque = deque(maxlen=MAX_HISTORY)
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._max_workers = max_workers
        self._running = False
        self._workers = []

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_workers)
        return self._semaphore

    async def start(self):
        """Start worker coroutines. Call once at app startup."""
        if self._running:
            return
        self._running = True
        for _ in range(self._max_workers):
            worker = asyncio.create_task(self._worker())
            self._workers.append(worker)
        logger.info(f"JobQueue started — {self._max_workers} workers")

    async def stop(self):
        """Graceful shutdown — wait for all pending jobs."""
        self._running = False
        for _ in self._workers:
            await self._queue.put(None)  # poison pill
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("JobQueue stopped")

    async def _worker(self):
        """Consume jobs from queue one at a time (semaphore enforces concurrency)."""
        while self._running:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            job, fn = item
            async with self._get_semaphore():
                await self._execute(job, fn)
            self._queue.task_done()

    async def _execute(self, job: Job, fn: Callable):
        job.status = "running"
        job.started_at = time.time()
        logger.info(f"Job started: {job.id[:8]} — {job.name}")
        try:
            # fn may be sync or async
            loop = asyncio.get_event_loop()
            if asyncio.iscoroutinefunction(fn):
                result = await fn()
            else:
                result = await loop.run_in_executor(None, fn)
            job.result = result
            job.status = "done"
            logger.info(f"Job done: {job.id[:8]} — {job.name}")
        except Exception as e:
            job.error = str(e)
            job.status = "error"
            logger.error(f"Job error: {job.id[:8]} — {job.name}: {e}")
        finally:
            job.finished_at = time.time()
            self._history.appendleft(job.to_dict())

    async def submit(self, name: str, fn: Callable,
                     meta: Optional[Dict] = None) -> str:
        """
        Submit a job for async execution.
        Returns the job ID immediately (non-blocking).
        """
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, name=name, meta=meta or {})
        self._jobs[job_id] = job
        await self._queue.put((job, fn))
        logger.info(f"Job queued: {job_id[:8]} — {name} (queue size={self._queue.qsize()})")
        return job_id

    def submit_sync(self, name: str, fn: Callable,
                    meta: Optional[Dict] = None) -> str:
        """
        Submit from a sync context (e.g. background_tasks.add_task).
        Schedules the job onto the running event loop.
        """
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.submit(name, fn, meta), loop
        )
        return future.result(timeout=5)

    def get_job(self, job_id: str) -> Optional[Dict]:
        job = self._jobs.get(job_id)
        if job:
            return job.to_dict()
        # Check history
        for h in self._history:
            if h["id"] == job_id:
                return h
        return None

    def list_jobs(self, status: str = "", limit: int = 50) -> list:
        """List recent jobs, optionally filtered by status."""
        jobs = list(self._history)
        if status:
            jobs = [j for j in jobs if j["status"] == status]
        return jobs[:limit]

    def stats(self) -> Dict:
        all_jobs = list(self._history)
        counts = {"pending": 0, "running": 0, "done": 0, "error": 0}
        for j in all_jobs:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        return {
            "queue_size": self._queue.qsize(),
            "max_workers": self._max_workers,
            "total_jobs": len(all_jobs),
            "status_counts": counts,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_queue: Optional[JobQueue] = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue


async def submit_job(name: str, fn: Callable,
                     meta: Optional[Dict] = None) -> str:
    """Convenience shortcut — submit to global queue."""
    q = get_queue()
    if not q._running:
        await q.start()
    return await q.submit(name, fn, meta)
