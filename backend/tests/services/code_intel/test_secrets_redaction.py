"""Secret scrubbing runs BEFORE embedding: hard secrets drop the chunk, softer
matches are redacted, and no secret substring survives in the output."""
from app.services.code_intel.secrets import redact


def test_private_key_drops_whole_chunk():
    content = "x = 1\n-----BEGIN RSA PRIVATE KEY-----\nMIIEabc...\n-----END RSA PRIVATE KEY-----\n"
    out, hard, n = redact(content)
    assert hard is True
    assert out == ""
    assert n >= 1


def test_aws_key_redacted():
    content = 'aws_key = "AKIAIOSFODNN7EXAMPLE"'
    out, hard, n = redact(content)
    assert hard is False
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "<REDACTED" in out and n >= 1


def test_db_url_with_creds_redacted():
    content = "DATABASE_URL = 'postgresql://admin:sup3rSecretPw@db.internal:5432/prod'"
    out, hard, n = redact(content)
    assert "sup3rSecretPw" not in out
    assert n >= 1


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    out, hard, n = redact(f"token = '{jwt}'")
    assert jwt not in out
    assert n >= 1


def test_openai_and_github_tokens_redacted():
    content = "k1 = 'sk-abcdefghij0123456789ABCDEF'\nk2 = 'ghp_abcdefghij0123456789ABCDEFGHIJ01'"
    out, _, n = redact(content)
    assert "sk-abcdefghij0123456789ABCDEF" not in out
    assert "ghp_abcdefghij0123456789ABCDEFGHIJ01" not in out
    assert n >= 2


def test_ordinary_code_is_not_mangled():
    content = (
        "def compute_average(values):\n"
        "    total = sum(values)\n"
        "    return total / len(values)  # simple mean\n"
    )
    out, hard, n = redact(content)
    assert hard is False
    assert out == content   # nothing redacted
    assert n == 0


def test_single_case_hex_and_lowercase_alnum_secrets_redacted():
    cases = [
        ("SESSION_SECRET = 9f8e7d6c5b4a39281706f5e4d3c2b1a0f1e2d3c4",
         "9f8e7d6c5b4a39281706f5e4d3c2b1a0f1e2d3c4"),           # 40 lowercase hex
        ('tok = "k3j5h2g8f9d0s7a1q4w6e8r0t2y5u3i7pass8x"',
         "k3j5h2g8f9d0s7a1q4w6e8r0t2y5u3i7pass8x"),             # lowercase alnum
    ]
    for content, needle in cases:
        out, hard, n = redact(content)
        assert needle not in out and n >= 1


def test_modern_openai_and_github_pat_redacted():
    content = (
        "a = 'sk-proj-T3BlbmFIabcdefghij0123456789KLMN'\n"
        "b = 'github_pat_11ABCDEFG0123456789abcdefghij0123456789abcdefKLM'"
    )
    out, _, n = redact(content)
    assert "sk-proj-T3BlbmFIabcdefghij0123456789KLMN" not in out
    assert "github_pat_11ABCDEFG0123456789abcdefghij0123456789abcdefKLM" not in out
    assert n >= 2


def test_inline_secret_assignment_redacted():
    content = 'password = "hunter2hunter2hunter2"'
    out, _, n = redact(content)
    assert "hunter2hunter2hunter2" not in out
    assert n >= 1
