"""W-MOS shared filesystem helpers: data root, atomic JSON, JSONL append/read.

All W-MOS state lives under data/launches/portfolio/ (override WMOS_DATA_PATH for
tests / Railway volume). Env is read at call-time so tests can monkeypatch per-test.
Mirrors the atomic-write convention in core/siteboost_scheduler.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA = ROOT / "data" / "launches" / "portfolio"


def data_root() -> Path:
    return Path(os.getenv("WMOS_DATA_PATH", str(_DEFAULT_DATA)))


def business_dir(slug: str) -> Path:
    return data_root() / slug


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
