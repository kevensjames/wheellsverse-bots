"""Kill switches — env-var-based disables matching the OMC convention.

  SUPREMA_DISABLE=1                              → disable autorepair entirely
  SUPREMA_SKIP=pattern1,pattern2                 → skip specific patterns
  SUPREMA_SKIP_PROJECTS=narai,nexora             → skip specific projects
  SUPREMA_DRY_RUN=1                              → force dry-run regardless of flags
  SUPREMA_NO_COMMIT=1                            → never auto-commit (still applies fixes)
  SUPREMA_NO_NOTIFY=1                            → never send notifications

Per-project overrides via `<project>/.suprema/config.yml`:

  enabled: true
  skip_patterns: [missing_pwa_manifest]
  safety_override:
    malformed_api_helper_call: review   # demote auto-safe → review for this project
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:
    import yaml  # optional; falls back to json
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


def disabled_globally() -> bool:
    return os.getenv("SUPREMA_DISABLE", "").strip() in ("1", "true", "yes")


def force_dry_run() -> bool:
    return os.getenv("SUPREMA_DRY_RUN", "").strip() in ("1", "true", "yes")


def block_commits() -> bool:
    return os.getenv("SUPREMA_NO_COMMIT", "").strip() in ("1", "true", "yes")


def block_notifications() -> bool:
    return os.getenv("SUPREMA_NO_NOTIFY", "").strip() in ("1", "true", "yes")


def skipped_patterns() -> set[str]:
    raw = os.getenv("SUPREMA_SKIP", "").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def skipped_projects() -> set[str]:
    raw = os.getenv("SUPREMA_SKIP_PROJECTS", "").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def project_config(project: Path) -> dict:
    """Read `<project>/.suprema/config.yml` (or `.json`). Returns {} if absent."""
    base = project / ".suprema"
    for name in ("config.yml", "config.yaml", "config.json"):
        p = base / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
            if name.endswith(".json"):
                return json.loads(text)
            if HAVE_YAML:
                return yaml.safe_load(text) or {}
            # YAML file but no yaml module — best-effort parse via json
            try:
                return json.loads(text)
            except Exception:
                return {}
        except Exception:
            return {}
    return {}


def effective_safety(project: Path, pattern: str, default_safety: str) -> str:
    """If the project's .suprema/config.yml has a safety_override.{pattern}
    entry, return that. Otherwise return the catalog's default."""
    cfg = project_config(project)
    override = (cfg.get("safety_override") or {}).get(pattern)
    if override in ("auto-safe", "review", "blocked"):
        return override
    return default_safety


def project_enabled(project: Path) -> bool:
    cfg = project_config(project)
    return bool(cfg.get("enabled", True))


def project_skips_pattern(project: Path, pattern: str) -> bool:
    cfg = project_config(project)
    return pattern in (cfg.get("skip_patterns") or [])
