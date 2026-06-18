import json

import pytest

from app.services.security.models import Finding, SecuritySnapshot
from app.services.security.store import SecurityStore


def test_write_then_read_latest_roundtrip(tmp_path):
    store = SecurityStore(tmp_path)
    snap = SecuritySnapshot(by="on-demand")
    store.write_latest(snap)
    got = store.read_latest()
    assert got is not None
    assert got.by == "on-demand"


def test_read_latest_missing_returns_none(tmp_path):
    assert SecurityStore(tmp_path).read_latest() is None


def test_request_marker_lifecycle(tmp_path):
    store = SecurityStore(tmp_path)
    assert store.consume_request() is False
    store.request_scan()
    assert store.consume_request() is True
    assert store.consume_request() is False


def test_append_findings_rejects_raw_secret_key(tmp_path):
    store = SecurityStore(tmp_path)
    bad = Finding.create("secret", "high", "gitleaks", "k", "f:1")
    # smuggle a raw secret into metadata under a forbidden key
    bad.metadata["secret"] = "AKIA-LEAK"
    with pytest.raises(ValueError):
        store.append_findings([bad])
    # nothing should have been written
    assert not (tmp_path / "secrets.jsonl").exists()


def test_append_findings_writes_jsonl(tmp_path):
    store = SecurityStore(tmp_path)
    f = Finding.create("vuln", "critical", "trivy", "CVE-2024-0001", "pkg:requests")
    store.append_findings([f])
    line = (tmp_path / "vulns.jsonl").read_text().strip()
    assert json.loads(line)["fingerprint"] == f.fingerprint
