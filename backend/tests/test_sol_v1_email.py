"""Stage 20 tests — Sol v1 email notification channel.

The email channel is opt-in (SOL_NOTIFY_EMAIL_ENABLED) AND requires SMTP config;
it is fully fail-soft (a send error never breaks the in-app notification). All
offline via monkeypatch — no DB, no real SMTP. NON-CUSTODIAL: email carries the
same text as the in-app nudge; no money.
"""
from __future__ import annotations

from uuid import uuid4

from app.config import settings
from app.services.sol_v1 import notifications as N


def test_email_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    assert N._email_configured() is True
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert N._email_configured() is False


def test_deliver_external_emails_when_enabled_and_configured(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(N, "_resolve_email", lambda db, user_id: "bob@example")
    sent = []
    monkeypatch.setattr(N, "_send_email", lambda to, subject, body: sent.append((to, subject, body)))

    N._deliver_external(object(), user_id=uuid4(), kind="payment_due",
                        title="Payment due", body="Pay $30")
    assert sent == [("bob@example", "Payment due", "Pay $30")]


def test_no_email_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", False)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    called = []
    monkeypatch.setattr(N, "_send_email", lambda *a, **k: called.append(1))

    N._deliver_external(object(), user_id=uuid4(), kind="payment_due", title="t", body="b")
    assert called == []


def test_no_email_when_enabled_but_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "")   # no SMTP host
    monkeypatch.setattr(settings, "SMTP_FROM", "")
    called = []
    monkeypatch.setattr(N, "_send_email", lambda *a, **k: called.append(1))

    N._deliver_external(object(), user_id=uuid4(), kind="payment_due", title="t", body="b")
    assert called == []


def test_email_send_failure_is_fail_soft(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(N, "_resolve_email", lambda db, user_id: "bob@example")

    def _boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(N, "_send_email", _boom)
    # must NOT raise — the in-app notification already landed
    N._deliver_external(object(), user_id=uuid4(), kind="payment_due", title="t", body="b")


def test_no_email_when_member_has_no_address(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(N, "_resolve_email", lambda db, user_id: None)  # no address on file
    called = []
    monkeypatch.setattr(N, "_send_email", lambda *a, **k: called.append(1))

    N._deliver_external(object(), user_id=uuid4(), kind="payment_due", title="t", body="b")
    assert called == []


def test_send_email_builds_and_sends_over_smtp(monkeypatch):
    import smtplib

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_PORT", 2525)
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(settings, "SMTP_USER", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)

    captured = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=10):
            captured["host"], captured["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            captured["tls"] = True

        def login(self, u, p):
            captured["login"] = (u, p)

        def send_message(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    N._send_email("bob@example", "Payment due", "Your $30 contribution is due.")

    assert captured["host"] == "smtp.example" and captured["port"] == 2525
    assert captured["tls"] is True and captured["login"] == ("user", "pass")
    msg = captured["msg"]
    assert msg["To"] == "bob@example" and msg["From"] == "sol@example"
    assert msg["Subject"] == "Payment due"
    assert "Your $30 contribution is due." in msg.get_content()
