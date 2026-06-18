from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Finding, SecuritySnapshot

_FORBIDDEN_KEYS = {"secret", "raw", "raw_secret", "password", "value"}
_CATEGORY_FILE = {"secret": "secrets.jsonl", "vuln": "vulns.jsonl", "backup": "backup.jsonl"}


class SecurityStore:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def default_dir() -> Path:
        env = os.environ.get("KAI_SECURITY_DIR")
        if env:
            return Path(env)
        # backend/app/services/security/store.py -> repo root is parents[4]
        return Path(__file__).resolve().parents[4] / "data" / "security"

    def _check_redacted(self, record: dict) -> None:
        if not record.get("fingerprint"):
            raise ValueError("finding missing fingerprint — refusing to persist")
        meta = record.get("metadata") or {}
        for k in meta:
            if str(k).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"forbidden raw-secret key in finding metadata: {k}")

    def append_findings(self, findings: list[Finding]) -> None:
        # validate ALL before writing ANY (no partial writes)
        records = [f.model_dump() for f in findings]
        for r in records:
            self._check_redacted(r)
        buckets: dict[str, list[str]] = {}
        for r in records:
            fname = _CATEGORY_FILE.get(r["category"], "other.jsonl")
            buckets.setdefault(fname, []).append(json.dumps(r))
        for fname, lines in buckets.items():
            with (self.base / fname).open("a", encoding="utf-8") as fh:
                for ln in lines:
                    fh.write(ln + "\n")

    def write_latest(self, snapshot: SecuritySnapshot) -> None:
        tmp = self.base / "latest.json.tmp"
        tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.base / "latest.json")

    def read_latest(self) -> SecuritySnapshot | None:
        p = self.base / "latest.json"
        if not p.exists():
            return None
        return SecuritySnapshot.model_validate_json(p.read_text(encoding="utf-8"))

    def request_scan(self) -> None:
        (self.base / ".request").write_text("1", encoding="utf-8")

    def consume_request(self) -> bool:
        p = self.base / ".request"
        if p.exists():
            p.unlink()
            return True
        return False
