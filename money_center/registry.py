#!/usr/bin/env python3
"""
money_center/registry.py
─────────────────────────────────────────────────────────────────────────────
Asset registry: load, save, validate, backup, and query functions.
All public functions are unit-tested in tests/test_registry.py.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ─── Paths ────────────────────────────────────────────────────────────────────

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "config.yaml"
ASSETS_FILE = HERE / "assets.json"
BACKUP_FILE = HERE / "assets.backup.json"
LOG_FILE = HERE / "logs" / "money_center.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# ─── Config ───────────────────────────────────────────────────────────────────

def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f) or {}
    return {
        "root_path": "/Users/jhonwheeler/wheellsverse_bots",
        "dashboard_port": 7777,
        "ssd_volume": "/Volumes/Wheellsverse",
        "auto_backup": True,
        "log_level": "INFO",
    }

_cfg = load_config()

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, _cfg.get("log_level", "INFO").upper(), logging.INFO),
    format="%(message)s",
)
logger = logging.getLogger("money_center")

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_file_handler)


def _log(level: str, asset_id: str, action: str, message: str):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} | {level.upper()} | {asset_id} | {action} | {message}"
    getattr(logger, level.lower(), logger.info)(line)


# ─── SSD Guard ────────────────────────────────────────────────────────────────

def check_ssd() -> bool:
    """Return True if the SSD volume is mounted and accessible."""
    ssd = Path(_cfg.get("ssd_volume", "/Volumes/Wheellsverse"))
    return ssd.exists() and ssd.is_dir()


def require_ssd():
    """Abort with a clear message if the SSD is not mounted."""
    if not check_ssd():
        ssd = _cfg.get("ssd_volume", "/Volumes/Wheellsverse")
        raise RuntimeError(
            f"SSD not mounted: '{ssd}' is not accessible.\n"
            "Connect the SSD drive and try again."
        )


# ─── Schema ───────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = {
    "id", "name", "category", "description", "revenue_model",
    "monthly_estimate_usd", "status", "run_command", "stop_command",
    "working_dir", "created_at", "updated_at",
}

VALID_CATEGORIES = {"bot", "product", "content", "service", "platform"}
VALID_STATUSES = {"idle", "running", "stopped", "error"}

ASSET_DEFAULTS: Dict[str, Any] = {
    "time_to_first_revenue_days": 0,
    "last_run": None,
    "last_stop": None,
    "last_revenue_check": None,
    "total_revenue_usd": 0,
    "tags": [],
    "notes": "",
}


def validate(asset: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors. Empty list = valid."""
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in asset:
            errors.append(f"Missing required field: '{field}'")

    if "id" in asset and not asset["id"].replace("_", "").replace("-", "").isalnum():
        errors.append(f"'id' must be alphanumeric slug: '{asset['id']}'")

    if "category" in asset and asset["category"] not in VALID_CATEGORIES:
        errors.append(f"'category' must be one of {sorted(VALID_CATEGORIES)}")

    if "status" in asset and asset["status"] not in VALID_STATUSES:
        errors.append(f"'status' must be one of {sorted(VALID_STATUSES)}")

    est = asset.get("monthly_estimate_usd", {})
    if not isinstance(est, dict) or not all(k in est for k in ("low", "mid", "high")):
        errors.append("'monthly_estimate_usd' must have keys: low, mid, high")

    # Validate run_command and stop_command for security
    run_cmd = asset.get("run_command", "").strip()
    stop_cmd = asset.get("stop_command", "").strip()
    
    if run_cmd:
        cmd_errors = _validate_command(run_cmd, "run_command")
        errors.extend(cmd_errors)
    
    if stop_cmd:
        cmd_errors = _validate_command(stop_cmd, "stop_command")
        errors.extend(cmd_errors)

    return errors


def _validate_command(cmd: str, field_name: str) -> List[str]:
    """
    Validate a command string for security issues.
    Returns a list of validation errors.
    """
    errors = []
    
    # Check for shell metacharacters that could enable command injection
    dangerous_chars = [";", "|", "&", "$", "`", "$(", "||", "&&", ">", "<", ">>"]
    for char in dangerous_chars:
        if char in cmd:
            errors.append(
                f"'{field_name}' contains dangerous shell metacharacter '{char}'. "
                f"Commands are executed without shell expansion for security."
            )
    
    # Try to parse the command with shlex to ensure it's valid
    try:
        shlex.split(cmd)
    except ValueError as e:
        errors.append(f"'{field_name}' has invalid syntax: {e}")
    
    # Check for absolute path or whitelisted commands
    cmd_parts = cmd.split()
    if cmd_parts:
        executable = cmd_parts[0]
        # Allow absolute paths or common safe executables
        if not (executable.startswith("/") or executable in [
            "python", "python3", "node", "npm", "java", "ruby", "perl",
            "bash", "sh", "pkill", "kill", "systemctl", "service"
        ]):
            # Warn but don't block - this is informational
            pass
    
    return errors


# ─── Persistence ──────────────────────────────────────────────────────────────

def load() -> List[Dict[str, Any]]:
    """Load assets from disk. Returns empty list if file missing."""
    require_ssd()
    if not ASSETS_FILE.exists():
        return []
    try:
        assets = json.loads(ASSETS_FILE.read_text(encoding="utf-8"))
        # Apply defaults for any missing optional fields
        for a in assets:
            for k, v in ASSET_DEFAULTS.items():
                a.setdefault(k, v)
        return assets
    except json.JSONDecodeError as e:
        _log("error", "registry", "load", f"Corrupt assets.json: {e}")
        raise


def backup():
    """Copy assets.json → assets.backup.json."""
    if ASSETS_FILE.exists():
        shutil.copy2(ASSETS_FILE, BACKUP_FILE)
        _log("info", "registry", "backup", f"Backed up to {BACKUP_FILE}")


def save(assets: List[Dict[str, Any]]):
    """Validate all assets, backup, then write assets.json atomically."""
    require_ssd()
    for asset in assets:
        errors = validate(asset)
        if errors:
            raise ValueError(f"Invalid asset '{asset.get('id', '?')}': {errors}")

    if _cfg.get("auto_backup", True):
        backup()

    tmp = ASSETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ASSETS_FILE)
    _log("info", "registry", "save", f"{len(assets)} assets saved")


# ─── Query helpers ────────────────────────────────────────────────────────────

def get(asset_id: str) -> Optional[Dict[str, Any]]:
    """Return a single asset by id, or None."""
    for a in load():
        if a["id"] == asset_id:
            return a
    return None


def exists(asset_id: str) -> bool:
    return get(asset_id) is not None


def upsert(asset: Dict[str, Any]):
    """Insert or update an asset (matched by id)."""
    assets = load()
    for i, a in enumerate(assets):
        if a["id"] == asset["id"]:
            assets[i] = asset
            save(assets)
            return
    assets.append(asset)
    save(assets)


def remove(asset_id: str) -> bool:
    """Delete an asset by id. Returns True if found and removed."""
    assets = load()
    new = [a for a in assets if a["id"] != asset_id]
    if len(new) == len(assets):
        return False
    save(new)
    _log("info", asset_id, "remove", "Asset removed from registry")
    return True


def update_status(asset_id: str, status: str, field: Optional[str] = None):
    """Set status and optionally stamp a timestamp field (last_run, last_stop…)."""
    asset = get(asset_id)
    if asset is None:
        raise KeyError(f"Asset not found: '{asset_id}'")
    asset["status"] = status
    asset["updated_at"] = datetime.now(timezone.utc).isoformat()
    if field:
        asset[field] = asset["updated_at"]
    upsert(asset)
    _log("info", asset_id, f"status→{status}", f"Field updated: {field or 'none'}")


# ─── Revenue helpers ──────────────────────────────────────────────────────────

def revenue_summary(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate monthly estimates, grouped by category."""
    by_cat: Dict[str, Dict[str, float]] = {}
    totals = {"low": 0.0, "mid": 0.0, "high": 0.0}

    for a in assets:
        cat = a.get("category", "other")
        est = a.get("monthly_estimate_usd", {"low": 0, "mid": 0, "high": 0})
        if cat not in by_cat:
            by_cat[cat] = {"low": 0.0, "mid": 0.0, "high": 0.0}
        for k in ("low", "mid", "high"):
            by_cat[cat][k] += est.get(k, 0)
            totals[k] += est.get(k, 0)

    return {"by_category": by_cat, "total": totals}


def new_asset_template() -> Dict[str, Any]:
    """Return an empty asset dict with all required fields pre-filled."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": "",
        "name": "",
        "category": "service",
        "description": "",
        "revenue_model": "other",
        "monthly_estimate_usd": {"low": 0, "mid": 0, "high": 0},
        "time_to_first_revenue_days": 30,
        "status": "idle",
        "last_run": None,
        "last_stop": None,
        "last_revenue_check": None,
        "total_revenue_usd": 0,
        "run_command": "",
        "stop_command": "",
        "working_dir": str(Path(_cfg.get("root_path", "/Users/jhonwheeler/wheellsverse_bots"))),
        "tags": [],
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }
