"""self_heal — KAI's BOUNDED self-healing.

Detect common operational issues and auto-fix ONLY a narrow allowlist of safe,
reversible actions. Everything risky (code edits, commits, git, killing
processes, deleting non-cache files) is NEVER auto-done — it's detected and
reported for human approval.

Safety model (load-bearing):
  - Detection is read-only and always safe.
  - Auto-fix runs ONLY when KAI_SELF_HEAL_ENABLED is set (default OFF) — the
    operator must explicitly authorize autonomous mutation.
  - The auto-fix allowlist is SAFE + REVERSIBLE only:
      • model_map_gap  → extend OLLAMA_MODEL_MAP for model-not-found 404s
                         (config edit, .env backed up first, JSON validated,
                         only ADDS keys — never modifies/removes existing)
      • disk           → delete __pycache__ dirs (regenerated; never logs/data)
  - Fail-soft throughout: a detector or fixer error degrades to "skipped",
    never raises out of detect()/heal().

This is the safe core of "let KAI fix things itself": real autonomy for the
boring/common cases, fenced so it can't damage the system or lose work.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO = Path(os.environ.get("KAI_REPO_ROOT") or Path(__file__).resolve().parents[3])
_ENV = _REPO / ".env"
_LOGS = _REPO / "logs"
_DEFAULT_LOCAL = "qwen2.5:7b"
_LIGHT_LOCAL = "llama3.2:latest"
_DISK_THRESHOLD = 0.85  # fraction used
_MODEL_NOT_FOUND = re.compile(r"model '([^']+)' not found")


def self_heal_enabled() -> bool:
    """KAI_SELF_HEAL_ENABLED gates AUTO-fix (default off). Detection is always
    allowed; only the mutating fixers check this."""
    return os.environ.get("KAI_SELF_HEAL_ENABLED", "").strip().lower() in (
        "1", "true", "yes",
    )


def _pick_local(model: str) -> str:
    """Map an unknown cloud model id to a sensible local model: light models →
    llama3.2, heavier ones → qwen2.5. Mirrors the existing OLLAMA_MODEL_MAP."""
    m = model.lower()
    if "haiku" in m or "mini" in m or "3.5-turbo" in m or "flash" in m:
        return _LIGHT_LOCAL
    return _DEFAULT_LOCAL


def _read_model_map() -> dict[str, str]:
    try:
        for line in _ENV.read_text().splitlines():
            if line.startswith("OLLAMA_MODEL_MAP="):
                return json.loads(line.split("=", 1)[1])
    except Exception:
        pass
    return {}


# ─── detectors (read-only, fail-soft) ────────────────────────────────


def _detect_model_map_gaps() -> dict[str, Any] | None:
    try:
        if not _LOGS.exists():
            return None
        counts: dict[str, int] = {}
        for log in _LOGS.glob("*.log"):
            try:
                txt = log.read_text(errors="ignore")
            except Exception:
                continue
            for name in _MODEL_NOT_FOUND.findall(txt):
                counts[name] = counts.get(name, 0) + 1
        current = _read_model_map()
        unmapped = {k: v for k, v in counts.items() if k not in current}
        if not unmapped:
            return None
        top = sorted(unmapped.items(), key=lambda x: -x[1])
        return {
            "kind": "model_map_gap", "auto_fixable": True,
            "detail": f"{len(unmapped)} unmapped model(s) causing 404s: "
                      + ", ".join(f"{k} (x{v})" for k, v in top[:5]),
            "models": [k for k, _ in top],
        }
    except Exception as e:
        logger.warning("self_heal: model-map detect failed: %s", e)
        return None


def _detect_disk() -> dict[str, Any] | None:
    try:
        u = shutil.disk_usage(str(_REPO))
        frac = u.used / u.total if u.total else 0
        if frac >= _DISK_THRESHOLD:
            return {
                "kind": "disk", "auto_fixable": True,
                "detail": f"disk {frac * 100:.0f}% used ({u.free // 2**30}GB free)",
            }
    except Exception as e:
        logger.warning("self_heal: disk detect failed: %s", e)
    return None


def detect() -> list[dict[str, Any]]:
    """All detected issues (read-only)."""
    return [d for d in (_detect_model_map_gaps(), _detect_disk()) if d]


# ─── auto-fixers (allowlist: safe + reversible only) ─────────────────


def _fix_model_map_gap(models: list[str]) -> dict[str, Any]:
    """Add missing model->local mappings to OLLAMA_MODEL_MAP. Backs up .env,
    validates JSON, ONLY adds keys. Reversible (restore the backup)."""
    if not _ENV.exists():
        return {"ok": False, "detail": ".env not found"}
    lines = _ENV.read_text().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.startswith("OLLAMA_MODEL_MAP="):
            continue
        try:
            m = json.loads(line.split("=", 1)[1])
        except Exception as e:
            return {"ok": False, "detail": f"OLLAMA_MODEL_MAP not valid JSON: {e}"}
        added = {}
        for model in models:
            if model and model not in m:
                m[model] = _pick_local(model)
                added[model] = m[model]
        if not added:
            return {"ok": True, "detail": "already mapped", "added": {}}
        backup = _ENV.parent / f".env.bak.selfheal-{int(time.time())}"
        shutil.copy(_ENV, backup)
        lines[i] = "OLLAMA_MODEL_MAP=" + json.dumps(m, separators=(",", ":")) + "\n"
        _ENV.write_text("".join(lines))
        return {"ok": True, "detail": f"added {len(added)} mapping(s)",
                "added": added, "backup": str(backup)}
    return {"ok": False, "detail": "OLLAMA_MODEL_MAP line not found"}


def _fix_disk() -> dict[str, Any]:
    """Delete __pycache__ dirs under the repo (regenerated; never logs/data)."""
    removed = 0
    try:
        for d in _REPO.rglob("__pycache__"):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    except Exception as e:
        return {"ok": False, "detail": f"cleanup error: {e}", "removed": removed}
    return {"ok": True, "detail": f"removed {removed} __pycache__ dir(s)", "removed": removed}


def heal(*, apply: bool = False) -> dict[str, Any]:
    """Detect issues; when apply=True AND KAI_SELF_HEAL_ENABLED is set, run the
    safe auto-fixers for auto-fixable issues. Returns a structured report.

    apply=False is a dry-run: detect + say what WOULD be fixed, change nothing.
    """
    issues = detect()
    report = {
        "detected": issues,
        "applied": [],
        "skipped_disabled": False,
        "note": "",
    }
    if not apply:
        report["note"] = (
            f"dry-run: {len(issues)} issue(s) detected; "
            f"{sum(1 for i in issues if i['auto_fixable'])} auto-fixable. "
            "Call with apply=true (and KAI_SELF_HEAL_ENABLED=1) to fix."
        )
        return report
    if not self_heal_enabled():
        report["skipped_disabled"] = True
        report["note"] = "auto-fix is disabled — set KAI_SELF_HEAL_ENABLED=1 to authorize."
        return report

    for issue in issues:
        if not issue.get("auto_fixable"):
            continue
        if issue["kind"] == "model_map_gap":
            res = _fix_model_map_gap(issue.get("models", []))
        elif issue["kind"] == "disk":
            res = _fix_disk()
        else:
            continue
        report["applied"].append({"kind": issue["kind"], "result": res})
    report["note"] = (
        f"applied {len(report['applied'])} safe auto-fix(es); "
        "anything risky is left for operator approval."
    )
    return report
