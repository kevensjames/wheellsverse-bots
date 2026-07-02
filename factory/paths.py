"""Factory filesystem helpers. Isolated from W-MOS: all state under data/factory/
(override FACTORY_DATA_PATH). Reuses the atomic IO helpers from core.portfolio.paths."""
from __future__ import annotations

import os
from pathlib import Path

from core.portfolio.paths import (  # re-export — single source of truth for atomics
    append_jsonl,
    load_json,
    read_jsonl,
    save_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]          # wheellsverse-bots/
_DEFAULT_DATA = ROOT / "data" / "factory"

__all__ = [
    "data_root", "project_dir", "workspaces_root", "worktrees_root",
    "load_json", "save_json_atomic", "append_jsonl", "read_jsonl",
]


def data_root() -> Path:
    return Path(os.getenv("FACTORY_DATA_PATH", str(_DEFAULT_DATA)))


def project_dir(slug: str) -> Path:
    return data_root() / slug


def workspaces_root() -> Path:
    return data_root() / "workspaces"


def worktrees_root() -> Path:
    return data_root() / "worktrees"
