#!/usr/bin/env python3
"""KAI Security Center worker — runs scanners OUT OF PROCESS from the daemon.

Invoked by launchd (scheduled) or by the trigger wrapper when data/security/.request
exists. Writes redacted findings + latest.json that the daemon reads. The daemon
never imports or runs this file.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# make `app.*` importable when run as a standalone script
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.security.models import Posture, SecuritySnapshot  # noqa: E402
from app.services.security.runners.backup import run_backup_and_check  # noqa: E402
from app.services.security.runners.secrets import scan_secrets  # noqa: E402
from app.services.security.runners.vulns import scan_vulns  # noqa: E402
from app.services.security.score import compute_score  # noqa: E402
from app.services.security.store import SecurityStore  # noqa: E402

try:
    from app.services.governance import is_scope_enabled  # noqa: E402
except Exception:  # governance import must never crash the worker
    def is_scope_enabled(scope: str) -> bool:  # type: ignore
        return os.environ.get("KAI_SCOPE_SECURITY", "") in ("1", "true", "yes", "on")


def _plaintext_secret_files(repo: Path) -> list[str]:
    found = []
    for pat in (".env", ".env.bak", ".env.local"):
        p = repo / pat
        if p.exists():
            found.append(str(p))
    return found


def build_posture(plaintext_files: list[str]) -> Posture:
    scopes = [s.replace("KAI_SCOPE_", "").lower() for s in os.environ if s.startswith("KAI_SCOPE_")]
    return Posture(
        mfa_enabled=False,
        user_table_present=False,
        plaintext_secret_files=plaintext_files,
        rate_limiting_present=None,
        governance_ok=True,
        scopes_enabled=scopes,
    )


def run_scan(store, *, by, scan_paths, backup_repo, backup_paths, now_epoch) -> SecuritySnapshot:
    sec_findings, sec_status = scan_secrets(scan_paths)
    vuln_findings, vuln_status = scan_vulns(scan_paths)
    backup_status, restic_status = run_backup_and_check(backup_repo, backup_paths, now_epoch)

    findings = sec_findings + vuln_findings
    store.append_findings(findings)

    posture = build_posture(_plaintext_secret_files(_REPO))
    score = compute_score(findings, posture, backup_status,
                          secrets_scanned=all(s.ok for s in sec_status),
                          vulns_scanned=all(s.ok for s in vuln_status))
    snap = SecuritySnapshot(by=by, findings=findings, backup=backup_status,
                            runner_status=sec_status + vuln_status + [restic_status],
                            posture=posture, score=score)
    store.write_latest(snap)
    return snap


def _notify(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass


def main() -> int:
    if not is_scope_enabled("security.scan"):
        print("security.scan scope disabled; exiting")
        return 0
    base = SecurityStore.default_dir()
    store = SecurityStore(base)
    lock = base / ".lock"
    if lock.exists():
        print("another scan in progress; exiting")
        return 0
    lock.write_text(str(os.getpid()))
    try:
        by = "on-demand" if store.consume_request() else "scheduled"
        scan_paths = [p for p in os.environ.get(
            "KAI_SECURITY_SCAN_PATHS", str(_REPO)).split(":") if p]
        backup_repo = os.environ.get("RESTIC_REPOSITORY", "")
        backup_paths = [p for p in os.environ.get(
            "KAI_SECURITY_BACKUP_PATHS", str(_REPO / "data")).split(":") if p]
        snap = run_scan(store, by=by, scan_paths=scan_paths, backup_repo=backup_repo,
                        backup_paths=backup_paths, now_epoch=time.time())
        crit = [f for f in snap.findings if f.severity == "critical" or f.verified]
        if crit:
            _notify(f"🔐 KAI Security: {len(crit)} critical/verified finding(s). "
                    f"Score={snap.score.overall}. Check the Security tab.")
        print(f"scan complete: {len(snap.findings)} findings, score={snap.score.overall}")
        return 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
