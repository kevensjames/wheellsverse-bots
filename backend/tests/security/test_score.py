from app.services.security.models import BackupStatus, Finding, Posture
from app.services.security.score import compute_score


def _posture(**kw):
    base = dict(mfa_enabled=False, user_table_present=False,
                plaintext_secret_files=[".env"], rate_limiting_present=None,
                governance_ok=True, scopes_enabled=["security"])
    base.update(kw)
    return Posture(**base)


def test_unknown_category_is_none_not_100():
    score = compute_score([], _posture(), BackupStatus(configured=False),
                           secrets_scanned=False, vulns_scanned=False)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Infrastructure / Vulns"] is None      # never scanned -> unknown
    assert cats["Backups"] == 0                          # not configured -> real 0
    # overall is capped below 100 while anything is unmonitored
    assert score.overall is not None and score.overall < 100


def test_honest_low_baseline_today():
    # today's reality: no MFA, plaintext .env on disk, no backups, no scans
    score = compute_score([], _posture(), BackupStatus(configured=False),
                          secrets_scanned=False, vulns_scanned=False)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Authentication"] <= 50
    assert cats["Backups"] == 0


def test_critical_findings_sink_categories():
    crit_secret = Finding.create("secret", "critical", "gitleaks", "AWS key", "x:1")
    crit_vuln = Finding.create("vuln", "critical", "trivy", "CVE", "pkg")
    score = compute_score([crit_secret, crit_vuln], _posture(plaintext_secret_files=[]),
                          BackupStatus(configured=True, check_ok=True, last_snapshot_age_s=3600),
                          secrets_scanned=True, vulns_scanned=True)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Infrastructure / Vulns"] < 60
    assert cats["Encryption / secrets-at-rest"] < 60


def test_strong_agent_security_when_governance_ok():
    score = compute_score([], _posture(), BackupStatus(configured=True, check_ok=True,
                          last_snapshot_age_s=3600), secrets_scanned=True, vulns_scanned=True)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Agent Security"] >= 80


def test_unchecked_rate_limiting_is_unknown_and_caps():
    # rate_limiting_present=None (the default in _posture) must yield score=None for API Security
    # and cap the overall below 100 (has_unknown path)
    score = compute_score(
        [],
        _posture(
            rate_limiting_present=None,
            plaintext_secret_files=[],
        ),
        BackupStatus(configured=True, check_ok=True, last_snapshot_age_s=3600),
        secrets_scanned=True,
        vulns_scanned=True,
    )
    cats = {c.name: c.score for c in score.categories}
    assert cats["API Security"] is None, "API Security must be None when rate-limiting was never checked"
    assert score.overall is not None and score.overall < 100, (
        "overall must be capped below 100 while API Security is unknown"
    )
