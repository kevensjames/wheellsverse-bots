#!/usr/bin/env python3
"""
core/log_aggregator.py
─────────────────────────────────────────────────────────────────────────────
Multi-source log aggregation.
Scans logs/bot_manager/*.log + logs/*.log
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("log_aggregator")

ROOT = Path(__file__).parent.parent
_LOG_DIRS = [ROOT / "logs" / "bot_manager", ROOT / "logs"]

_LEVEL_RE = re.compile(r'\b(ERROR|CRITICAL|WARNING|WARN|INFO|DEBUG)\b')


def _scan_sources() -> List[Dict]:
    """Return list of available log files."""
    seen = set()
    sources = []
    for d in _LOG_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.log")):
            if f in seen:
                continue
            seen.add(f)
            sources.append({
                "name": f.stem,
                "path": str(f),
                "dir": f.parent.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return sources


def get_sources() -> List[Dict]:
    return _scan_sources()


def tail_log(source_name: str, lines: int = 200) -> List[Dict]:
    """Return last N lines of a log file."""
    sources = {s["name"]: s for s in _scan_sources()}
    src = sources.get(source_name)
    if not src:
        return []
    path = Path(src["path"])
    try:
        content = path.read_text(errors="replace")
        all_lines = content.splitlines()[-lines:]
        return _parse_lines(all_lines, source_name)
    except Exception as e:
        return [{"text": f"Error reading log: {e}", "level": "ERROR", "source": source_name}]


def get_all_logs(since_minutes: int = 60) -> List[Dict]:
    """Return merged chronological log lines from all sources."""
    since = datetime.utcnow() - timedelta(minutes=since_minutes)
    all_entries = []
    for src in _scan_sources():
        try:
            path = Path(src["path"])
            if path.stat().st_mtime < since.timestamp():
                continue
            lines = path.read_text(errors="replace").splitlines()[-500:]
            all_entries.extend(_parse_lines(lines, src["name"]))
        except Exception:
            pass
    all_entries.sort(key=lambda x: x.get("ts", ""))
    return all_entries


def search_logs(query: str, source_name: Optional[str] = None, lines: int = 500) -> List[Dict]:
    """Search log content for a query string."""
    if not query.strip():
        return []
    ql = query.lower()
    results = []
    sources = _scan_sources()
    if source_name:
        sources = [s for s in sources if s["name"] == source_name]
    for src in sources:
        try:
            content = Path(src["path"]).read_text(errors="replace")
            for line in content.splitlines()[-lines:]:
                if ql in line.lower():
                    results.extend(_parse_lines([line], src["name"]))
        except Exception:
            pass
    return results[:200]


def get_log_stats() -> Dict:
    """Return error/warning counts per source."""
    stats = defaultdict(lambda: {"total": 0, "errors": 0, "warnings": 0})
    for src in _scan_sources():
        try:
            content = Path(src["path"]).read_text(errors="replace")
            for line in content.splitlines():
                name = src["name"]
                stats[name]["total"] += 1
                level = _get_level(line)
                if level in ("ERROR", "CRITICAL"):
                    stats[name]["errors"] += 1
                elif level in ("WARNING", "WARN"):
                    stats[name]["warnings"] += 1
        except Exception:
            pass
    return dict(stats)


def _get_level(line: str) -> str:
    m = _LEVEL_RE.search(line)
    return m.group(1) if m else "INFO"


def _parse_lines(lines: List[str], source: str) -> List[Dict]:
    result = []
    for line in lines:
        if not line.strip():
            continue
        level = _get_level(line)
        result.append({
            "text": line,
            "level": level,
            "source": source,
            "ts": _extract_ts(line),
        })
    return result


def _extract_ts(line: str) -> str:
    # Try to extract ISO timestamp from line
    m = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', line)
    return m.group(1) if m else ""
