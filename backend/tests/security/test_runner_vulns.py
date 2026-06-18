from pathlib import Path

from app.services.security.runners.vulns import parse_trivy

FIX = Path(__file__).parent / "fixtures"


def test_parse_trivy_maps_severity_and_pkg():
    findings = parse_trivy((FIX / "trivy.json").read_text())
    assert len(findings) == 2
    crit = [f for f in findings if f.severity == "critical"][0]
    assert crit.category == "vuln" and crit.tool == "trivy"
    assert "requests" in crit.location
    assert crit.title.startswith("CVE-2024-0001")


def test_parse_trivy_empty_results():
    assert parse_trivy('{"Results":[]}') == []
    assert parse_trivy("") == []


def test_parse_trivy_parses_secrets_and_misconfig_redacted():
    findings = parse_trivy((FIX / "trivy_full.json").read_text())
    secrets = [f for f in findings if f.category == "secret"]
    misconf = [f for f in findings if f.category == "vuln" and f.metadata.get("kind") == "misconfig"]
    assert len(secrets) == 1 and secrets[0].tool == "trivy"
    assert "AKIA9XYZ7QW2NB4VDLM0" not in str(secrets[0].model_dump())  # redacted to fingerprint
    assert len(misconf) == 1 and "DS002" in misconf[0].location
