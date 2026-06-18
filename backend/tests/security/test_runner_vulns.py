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
