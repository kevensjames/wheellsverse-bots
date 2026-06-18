import shutil
from pathlib import Path

import pytest

from app.services.security.runners.secrets import parse_gitleaks, parse_trufflehog, scan_secrets

FIX = Path(__file__).parent / "fixtures"


def test_parse_gitleaks_redacts():
    findings = parse_gitleaks((FIX / "gitleaks.json").read_text())
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "secret" and f.tool == "gitleaks"
    assert "AKIAIOSFODNN7EXAMPLE" not in str(f.model_dump())
    assert f.location == "data/.env:12"


def test_parse_trufflehog_verified_flag():
    findings = parse_trufflehog((FIX / "trufflehog.jsonl").read_text())
    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "trufflehog" and f.verified is True
    assert f.severity == "critical"  # verified live cred
    assert "AKIAIOSFODNN7EXAMPLE" not in str(f.model_dump())


def test_parse_gitleaks_empty():
    assert parse_gitleaks("") == []
    assert parse_gitleaks("[]") == []


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_scan_secrets_detects_real_leak_redacted(tmp_path):
    # Integration: exercises the REAL gitleaks CLI invocation (the part unit
    # tests can't cover). A Stripe key is reliably flagged; the canonical AWS
    # example key is allowlisted by gitleaks and intentionally not used here.
    (tmp_path / "creds.env").write_text('stripe = "sk_live_51H8xQ2eZvKYlo2C9bXcVbNmAsDfGhJkL"\n')
    findings, statuses = scan_secrets([str(tmp_path)])
    gl = [s for s in statuses if s.tool == "gitleaks"][0]
    assert gl.ok is True, f"gitleaks runner errored: {gl.error}"
    assert any(f.tool == "gitleaks" for f in findings), "gitleaks should detect the planted key"
    # redaction holds end-to-end: the raw key never appears in any finding
    assert all("sk_live_51H8xQ2eZvKYlo2C9bXcVbNmAsDfGhJkL" not in str(f.model_dump()) for f in findings)
