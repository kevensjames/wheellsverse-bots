#!/usr/bin/env python3
"""
core/bot_manager.py
─────────────────────────────────────────────────────────────────────────────
Subprocess-based bot process manager.
Manages all running bot processes in a dict keyed by bot name.
Each entry stores: Popen object, PID, start time, category, log file, status.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot_manager")

ROOT = Path(__file__).parent.parent
PYTHON = ROOT / "venv" / "bin" / "python3"
BOTS_DIR = ROOT / "bots"
LOG_DIR = ROOT / "logs" / "bot_manager"

LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─── Process Registry ─────────────────────────────────────────────────────────

# key: bot_name → {popen, pid, start_time, category, log_file, status}
_procs: Dict[str, Dict[str, Any]] = {}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _refresh_status(entry: Dict[str, Any]) -> str:
    """Poll the popen object and update the status field in-place."""
    code = entry["popen"].poll()
    if code is None:
        entry["status"] = "running"
    elif code == 0:
        entry["status"] = "idle"
    else:
        entry["status"] = "crashed"
    return entry["status"]


def _entry_to_dict(name: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-safe summary of a process entry."""
    return {
        "name": name,
        "pid": entry["pid"],
        "start_time": entry["start_time"],
        "uptime": round(time.time() - entry["start_time"], 1),
        "category": entry["category"],
        "log_file": entry["log_file"],
        "status": _refresh_status(entry),
    }


def _resolve_bot_path(bot_name: str, category: str = "") -> Optional[Path]:
    """
    Resolve the bot.py path for a given bot_name + category.
    Search order:
      1. bots/{category}/{bot_name}/bot.py  (if category given)
      2. bots/*/{bot_name}/bot.py           (glob fallback)
      3. generated_bots/{bot_name}.py
    """
    if category:
        p = BOTS_DIR / category / bot_name / "bot.py"
        if p.exists():
            return p

    # Glob fallback
    matches = list(BOTS_DIR.glob(f"*/{bot_name}/bot.py"))
    if matches:
        return matches[0]

    # generated bots
    p = ROOT / "generated_bots" / f"{bot_name}.py"
    if p.exists():
        return p

    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def start_bot(bot_name: str, category: str = "") -> Dict[str, Any]:
    """
    Start a bot subprocess.
    Returns the process entry dict (JSON-safe).
    Raises ValueError if bot is already running or path not found.
    """
    if bot_name in _procs and _refresh_status(_procs[bot_name]) == "running":
        raise ValueError(f"Bot '{bot_name}' is already running (PID {_procs[bot_name]['pid']})")

    bot_path = _resolve_bot_path(bot_name, category)
    if not bot_path:
        raise ValueError(f"Bot '{bot_name}' not found (searched bots/{category}/{bot_name}/bot.py and generated_bots/)")

    # Infer category from path if not supplied
    if not category and bot_path.parts[-3] != "bots":
        category = bot_path.parts[-2] if len(bot_path.parts) >= 3 else "unknown"
    if not category:
        # path is bots/{category}/{bot_name}/bot.py
        try:
            category = bot_path.relative_to(BOTS_DIR).parts[0]
        except Exception:
            category = "unknown"

    log_path = LOG_DIR / f"{bot_name}.log"
    log_fd = open(log_path, "a", encoding="utf-8")
    try:
        log_fd.write(f"\n{'=' * 60}\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting {bot_name}\n{'=' * 60}\n")
        log_fd.flush()

        popen = subprocess.Popen(
            [str(PYTHON), str(bot_path)],
            stdout=log_fd,
            stderr=log_fd,
            cwd=str(ROOT),
            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception:
        log_fd.close()
        raise

    entry = {
        "popen": popen,
        "pid": popen.pid,
        "start_time": time.time(),
        "category": category,
        "log_file": str(log_path),
        "log_fd": log_fd,
        "status": "running",
    }
    _procs[bot_name] = entry

    logger.info(f"[bot_manager] Started {bot_name} (PID={popen.pid}, path={bot_path})")
    return _entry_to_dict(bot_name, entry)


def stop_bot(bot_name: str) -> Dict[str, Any]:
    """
    Gracefully stop a bot subprocess (SIGTERM → wait 3s → SIGKILL).
    Raises ValueError if bot not found in registry.
    """
    if bot_name not in _procs:
        raise ValueError(f"Bot '{bot_name}' is not managed (never started or already removed)")

    entry = _procs[bot_name]
    popen = entry["popen"]

    if popen.poll() is None:
        popen.terminate()
        try:
            popen.wait(timeout=3)
        except subprocess.TimeoutExpired:
            popen.kill()
            popen.wait()

    # Close log file
    try:
        entry["log_fd"].close()
    except Exception:
        pass

    result = _entry_to_dict(bot_name, entry)
    result["status"] = "idle"
    del _procs[bot_name]

    logger.info(f"[bot_manager] Stopped {bot_name}")
    return result


def restart_bot(bot_name: str, category: str = "") -> Dict[str, Any]:
    """Stop then start a bot. Category is inferred from current entry if not supplied."""
    old_category = category
    if not old_category and bot_name in _procs:
        old_category = _procs[bot_name]["category"]

    if bot_name in _procs:
        stop_bot(bot_name)

    return start_bot(bot_name, old_category)


def bot_status(bot_name: str) -> Dict[str, Any]:
    """Return current status dict for a managed bot. Raises ValueError if unknown."""
    if bot_name not in _procs:
        raise ValueError(f"Bot '{bot_name}' is not managed")
    return _entry_to_dict(bot_name, _procs[bot_name])


def list_bots() -> List[Dict[str, Any]]:
    """Return status for all managed (running/crashed) bots."""
    return [_entry_to_dict(name, entry) for name, entry in _procs.items()]


def get_log(bot_name: str, lines: int = 100) -> str:
    """Return the last N lines of a bot's log file."""
    if bot_name in _procs:
        log_path = Path(_procs[bot_name]["log_file"])
    else:
        log_path = LOG_DIR / f"{bot_name}.log"

    if not log_path.exists():
        return f"No log found for '{bot_name}'"

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail = text.splitlines()[-lines:]
        return "\n".join(tail)
    except Exception as e:
        return f"Error reading log: {e}"


def revive_crashed(max_restarts: int = 3) -> List[Dict[str, Any]]:
    """
    Restart bots that have crashed. Respects a per-bot restart counter so
    a hard-crashing bot does not restart more than `max_restarts` times.
    Returns a list of revived bot entries.
    """
    revived = []
    for name, entry in list(_procs.items()):
        if _refresh_status(entry) == "crashed":
            restart_count = entry.get("_restart_count", 0)
            if restart_count >= max_restarts:
                logger.warning(f"[bot_manager] {name} has crashed {restart_count}x — not restarting")
                continue
            try:
                old_category = entry.get("category", "")
                stop_bot(name)
                new_entry = start_bot(name, old_category)
                _procs[name]["_restart_count"] = restart_count + 1
                revived.append(new_entry)
                logger.info(f"[bot_manager] Auto-restarted {name} (restart #{restart_count + 1})")
            except Exception as e:
                logger.error(f"[bot_manager] Failed to revive {name}: {e}")
    return revived


def discover_bots() -> List[Dict[str, Any]]:
    """
    Walk the bots/ directory and return metadata for every bot.py found.
    Also includes generated_bots/.
    """
    results: List[Dict[str, Any]] = []

    # bots/{category}/{bot_name}/bot.py
    for bot_path in sorted(BOTS_DIR.glob("*/*/bot.py")):
        parts = bot_path.relative_to(BOTS_DIR).parts
        if len(parts) >= 3:
            category = parts[0]
            bot_name = parts[1]
        else:
            category = "unknown"
            bot_name = parts[0]

        # Merge with running status if available
        status = "idle"
        pid = None
        if bot_name in _procs:
            status = _refresh_status(_procs[bot_name])
            pid = _procs[bot_name]["pid"]

        results.append({
            "name": bot_name,
            "category": category,
            "path": str(bot_path),
            "status": status,
            "pid": pid,
        })

    # generated_bots/*.py
    gen_dir = ROOT / "generated_bots"
    for py_path in sorted(gen_dir.glob("*.py")):
        bot_name = py_path.stem
        status = "idle"
        pid = None
        if bot_name in _procs:
            status = _refresh_status(_procs[bot_name])
            pid = _procs[bot_name]["pid"]
        results.append({
            "name": bot_name,
            "category": "generated",
            "path": str(py_path),
            "status": status,
            "pid": pid,
        })

    return results
