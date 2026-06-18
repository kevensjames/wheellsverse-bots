from pathlib import Path

from app.services.security.runners.secrets import parse_gitleaks, parse_trufflehog

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
