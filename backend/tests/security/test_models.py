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


def test_finding_create_no_secret_fingerprint_is_deterministic():
    kwargs = dict(
        category="vuln",
        severity="high",
        tool="bandit",
        title="SQL injection",
        location="app/db.py:42",
    )
    f1 = Finding.create(**kwargs)
    f2 = Finding.create(**kwargs)

    # fingerprint is valid 64-char hex
    assert len(f1.fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in f1.fingerprint)

    # deterministic for same title+location
    assert f1.fingerprint == f2.fingerprint

    # differs for a different location
    f_other = Finding.create(**{**kwargs, "location": "app/db.py:99"})
    assert f_other.fingerprint != f1.fingerprint
