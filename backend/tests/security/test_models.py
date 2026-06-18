from app.services.security.models import Finding


def test_finding_create_redacts_secret_and_fingerprints():
    f = Finding.create(
        category="secret",
        severity="critical",
        tool="gitleaks",
        title="AWS access key",
        location="data/.env:12",
        secret="AKIAIOSFODNN7EXAMPLE",
        verified=True,
    )
    dumped = f.model_dump()
    # the raw secret never appears anywhere in the persisted record
    assert "AKIAIOSFODNN7EXAMPLE" not in str(dumped)
    assert f.fingerprint and len(f.fingerprint) == 64  # sha256 hex
    assert f.verified is True
    assert f.id and f.ts
