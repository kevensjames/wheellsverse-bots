#!/usr/bin/env python3
"""
bots/core/bug_hunter/watchdog.py
─────────────────────────────────────────────────────────────────────────────
File-system watchdog that re-scans changed .py files in real time and
logs new findings. Uses polling (no watchdog lib dependency).
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import time
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from .scanner import Scanner, RawFinding
from .detector import Detector, Bug

logger = logging.getLogger("bug_hunter.watchdog")

ROOT = Path(__file__).parent.parent.parent.parent


class Watchdog:
    """
    Polls watched directories every `interval` seconds.
    Calls `on_new_bugs` whenever newly-introduced bugs are detected.
    """

    def __init__(
        self,
        watch_paths: Optional[List[Path]] = None,
        interval: int = 30,
        on_new_bugs: Optional[Callable[[List[Bug]], None]] = None,
    ):
        self.watch_paths = watch_paths or [ROOT / "bots", ROOT / "core"]
        self.interval = interval
        self.on_new_bugs = on_new_bugs or self._default_handler
        self._scanner = Scanner()
        self._detector = Detector()
        self._mtimes: Dict[str, float] = {}
        self._known_bugs: Set[str] = set()  # set of "file:line:kind" keys
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, blocking: bool = False):
        self._stop.clear()
        if blocking:
            self._loop()
        else:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="bug_hunter_watchdog")
            self._thread.start()
            logger.info("Watchdog started (background thread)")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Watchdog stopped")

    def _loop(self):
        logger.info(f"Watchdog polling every {self.interval}s — watching {[str(p) for p in self.watch_paths]}")
        while not self._stop.is_set():
            try:
                changed = self._get_changed_files()
                if changed:
                    self._scan_changed(changed)
            except Exception as e:
                logger.error(f"Watchdog loop error: {e}")
            self._stop.wait(self.interval)

    def _get_changed_files(self) -> List[Path]:
        changed = []
        for base in self.watch_paths:
            for py_file in base.rglob("*.py"):
                try:
                    mtime = py_file.stat().st_mtime
                    key = str(py_file)
                    if self._mtimes.get(key, 0) != mtime:
                        self._mtimes[key] = mtime
                        changed.append(py_file)
                except Exception:
                    pass
        return changed

    def _scan_changed(self, files: List[Path]):
        all_findings: List[RawFinding] = []
        for f in files:
            all_findings.extend(self._scanner.scan_file(f))

        new_bugs = self._detector.classify(all_findings)

        # Filter to bugs not seen before
        novel = []
        for bug in new_bugs:
            key = f"{bug.file}:{bug.line}:{bug.title}"
            if key not in self._known_bugs:
                self._known_bugs.add(key)
                novel.append(bug)

        if novel:
            logger.warning(f"Watchdog detected {len(novel)} new bug(s) in {len(files)} changed file(s)")
            self.on_new_bugs(novel)

    @staticmethod
    def _default_handler(bugs: List[Bug]):
        for bug in bugs:
            logger.warning(
                f"[{bug.severity}] {bug.id} {bug.file}:{bug.line} — {bug.title}"
            )
