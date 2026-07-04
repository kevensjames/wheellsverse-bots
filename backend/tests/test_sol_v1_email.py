"""Stage 20 tests — Sol v1 email notification channel.

Opt-in (SOL_NOTIFY_EMAIL_ENABLED) + requires SMTP config; delivery runs in a
BACKGROUND thread with its own session (never blocks/poisons the caller); TLS is
certificate-verified and AUTH is never sent over cleartext. All offline via
monkeypatch. NON-CUSTODIAL.
"""
from __future__ import annotations

import ssl
import threading
import time
from uuid import uuid4

import pytest

from app.config import settings
from app.services.sol_v1 import notifications as N


def test_email_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    assert N._email_configured() is True
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert N._email_configured() is False


# ── the synchronous unit (resolve + send) ──────────────────────────────────────


def test_deliver_email_sync_sends(monkeypatch):
    monkeypatch.setattr(N, "_resolve_email", lambda user_id: "bob@example")
    sent = []
    monkeypatch.setattr(N, "_send_email", lambda to, subject, body: sent.append((to, subject, body)))
    N._deliver_email_sync(uuid4(), "Payment due", "Pay $30")
    assert sent == [("bob@example", "Payment due", "Pay $30")]


def test_deliver_email_sync_no_address(monkeypatch):
    monkeypatch.setattr(N, "_resolve_email", lambda user_id: None)  # no address on file
    called = []
    monkeypatch.setattr(N, "_send_email", lambda *a: called.append(1))
    N._deliver_email_sync(uuid4(), "T", "B")
    assert called == []


# ── the background fan-out (opt-in + fail-soft) ────────────────────────────────


def test_deliver_external_fires_in_background(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    done = threading.Event()
    got = []

    def _fake(user_id, subject, body):
        got.append((subject, body))
        done.set()

    monkeypatch.setattr(N, "_deliver_email_sync", _fake)
    N._deliver_external(user_id=uuid4(), kind="payment_due", title="T", body="B")
    assert done.wait(timeout=3), "email background thread did not run"
    assert got == [("T", "B")]


def test_deliver_external_disabled_does_not_send(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", False)
    called = []
    monkeypatch.setattr(N, "_deliver_email_sync", lambda *a: called.append(1))
    N._deliver_external(user_id=uuid4(), kind="payment_due", title="T", body="B")
    time.sleep(0.1)
    assert called == []


def test_deliver_external_is_fail_soft(monkeypatch):
    monkeypatch.setattr(settings, "SOL_NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    done = threading.Event()

    def _boom(user_id, subject, body):
        done.set()
        raise RuntimeError("smtp down")

    monkeypatch.setattr(N, "_deliver_email_sync", _boom)
    N._deliver_external(user_id=uuid4(), kind="payment_due", title="T", body="B")  # must NOT raise
    assert done.wait(timeout=3)


# ── SMTP send: message build + TLS security ────────────────────────────────────


def test_send_email_verifies_tls_and_builds_message(monkeypatch):
    import smtplib

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_PORT", 2525)
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(settings, "SMTP_USER", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)
    cap = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=10):
            cap["host"], cap["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            cap["ctx"] = context

        def login(self, u, p):
            cap["login"] = (u, p)

        def send_message(self, msg):
            cap["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    N._send_email("bob@example", "Payment due", "Your $30 contribution is due.")

    assert cap["host"] == "smtp.example" and cap["port"] == 2525
    # a VERIFYING TLS context is passed (cert chain + hostname) — blocks MITM
    assert isinstance(cap["ctx"], ssl.SSLContext)
    assert cap["ctx"].verify_mode == ssl.CERT_REQUIRED and cap["ctx"].check_hostname is True
    assert cap["login"] == ("user", "pass")
    m = cap["msg"]
    assert m["To"] == "bob@example" and m["From"] == "sol@example" and m["Subject"] == "Payment due"
    assert "Your $30 contribution is due." in m.get_content()


def test_send_email_refuses_cleartext_auth(monkeypatch):
    import smtplib

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(settings, "SMTP_USER", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", False)  # cleartext channel
    logged_in = []

    class _FakeSMTP:
        def __init__(self, host, port, timeout=10):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, u, p):
            logged_in.append(1)

        def send_message(self, msg):
            pass

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    with pytest.raises(RuntimeError):
        N._send_email("bob@example", "S", "B")
    assert logged_in == []  # credentials NEVER sent over cleartext


def test_send_email_port_465_uses_implicit_tls(monkeypatch):
    import smtplib

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_PORT", 465)
    monkeypatch.setattr(settings, "SMTP_FROM", "sol@example")
    monkeypatch.setattr(settings, "SMTP_USER", "")
    used = {}

    class _FakeSMTPSSL:
        def __init__(self, host, port, timeout=10, context=None):
            used["port"], used["ctx"] = port, context

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            used["sent"] = True

    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    N._send_email("bob@example", "S", "B")
    assert used["port"] == 465 and isinstance(used["ctx"], ssl.SSLContext) and used["sent"] is True
