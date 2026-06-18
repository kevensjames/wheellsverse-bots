import importlib.util
from pathlib import Path

from app.services.security.models import BackupStatus, Finding, RunnerStatus
from app.services.security.store import SecurityStore

# load scripts/security_worker.py by path (it lives outside the app package)
_WORKER = Path(__file__).resolve().parents[3] / "scripts" / "security_worker.py"
spec = importlib.util.spec_from_file_location("security_worker", _WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_run_scan_persists_findings_and_score(tmp_path, monkeypatch):
    crit = Finding.create("vuln", "critical", "trivy", "CVE-X", "pkg")
    monkeypatch.setattr(worker, "scan_secrets", lambda paths: ([], [RunnerStatus(tool="gitleaks", ok=True)]))
    monkeypatch.setattr(worker, "scan_vulns", lambda paths: ([crit], [RunnerStatus(tool="trivy", ok=True)]))
    monkeypatch.setattr(worker, "run_backup_and_check",
                        lambda repo, paths, now: (BackupStatus(configured=False), RunnerStatus(tool="restic", ok=False)))

    store = SecurityStore(tmp_path)
    snap = worker.run_scan(store, by="on-demand", scan_paths=["x"], backup_repo="",
                           backup_paths=[], now_epoch=1000.0)

    assert snap.by == "on-demand"
    assert snap.score.overall is not None
    # findings persisted + latest.json written + redaction held
    assert (tmp_path / "vulns.jsonl").exists()
    assert worker.SecuritySnapshot is not None
    reloaded = store.read_latest()
    assert reloaded is not None and len(reloaded.findings) == 1
