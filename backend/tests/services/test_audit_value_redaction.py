"""Value-level secret scrubbing in the audit log (added for the SWE push path):
a token in a STRING value whose key isn't secret-looking must still be redacted."""
from app.services.governance.audit_log import _redact


def test_bearer_token_in_value_scrubbed():
    r = _redact({"note": "Authorization: Bearer ghs_abcdefghijklmnopqrstuvwxyz012345"})
    assert "ghs_" not in r["note"] and "<redacted>" in r["note"]


def test_token_in_positional_arg_list_scrubbed():
    r = _redact({"_args": ["clone", "https://x-access-token:ghp_abcdefghijklmnopqrst@github.com/o/r"]})
    joined = " ".join(r["_args"])
    assert "ghp_abcdefghijklmnopqrst" not in joined


def test_non_secret_value_untouched():
    assert _redact({"path": "/repo/src/lib.py"})["path"] == "/repo/src/lib.py"
