"""Security-guard tests for the Money Center dashboard.

The dashboard can launch arbitrary shell commands, so these verify the decisions
that keep it from being an unauthenticated network RCE:
  * loopback detection,
  * "no network bind without a token" fail-closed rule,
  * constant-time operator-token and CSRF-token checks.

They import only `money_center.security` (no Flask), so they run in any env.
"""
import importlib

import pytest

sec = importlib.import_module("money_center.security")


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True), ("localhost", True), ("::1", True),
    ("127.0.0.5", True), ("  LOCALHOST ", True),
    ("0.0.0.0", False), ("192.168.1.10", False), ("10.0.0.1", False),
    ("", False), ("example.com", False),
    # DNS names that merely START with '127.' must NOT be treated as loopback
    ("127.evil.com", False), ("127.0.0.1.evil.com", False),
])
def test_is_loopback(host, expected):
    assert sec.is_loopback(host) is expected


def test_network_bind_requires_token_off_loopback():
    # loopback is always allowed, with or without a token
    assert sec.network_bind_allowed("127.0.0.1", "") is True
    assert sec.network_bind_allowed("localhost", "tok") is True
    # a non-loopback bind is refused unless a token is configured
    assert sec.network_bind_allowed("0.0.0.0", "") is False
    assert sec.network_bind_allowed("0.0.0.0", "tok") is True
    assert sec.network_bind_allowed("192.168.1.5", "") is False


def test_token_valid():
    assert sec.token_valid("s3cret", "s3cret") is True
    assert sec.token_valid("wrong", "s3cret") is False
    assert sec.token_valid("", "s3cret") is False
    assert sec.token_valid("s3cret", "") is False   # never validate against an unset token
    assert sec.token_valid("", "") is False


def test_csrf_valid():
    t = sec.new_csrf_token()
    assert sec.csrf_valid(t, t) is True
    assert sec.csrf_valid(t, sec.new_csrf_token()) is False
    assert sec.csrf_valid("", t) is False
    assert sec.csrf_valid(t, "") is False


def test_new_csrf_token_is_random_hex():
    a, b = sec.new_csrf_token(), sec.new_csrf_token()
    assert a != b and len(a) >= 24 and all(c in "0123456789abcdef" for c in a)


@pytest.mark.parametrize("host_header,bound,ok", [
    ("127.0.0.1:7777", "127.0.0.1", True),
    ("localhost:7777", "127.0.0.1", True),
    ("[::1]:7777", "127.0.0.1", True),
    ("evil.com", "127.0.0.1", False),          # DNS-rebinding attempt
    ("evil.com:7777", "127.0.0.1", False),
    ("127.evil.com:7777", "127.0.0.1", False), # '127.'-prefix DNS-rebind bypass — must fail
    ("127.0.0.1.evil.com", "127.0.0.1", False),
    ("10.0.0.5:7777", "10.0.0.5", True),        # matches the configured bind host
    ("10.0.0.5:7777", "127.0.0.1", False),      # not loopback and not the bind host
    ("attacker.internal", "10.0.0.5", False),
])
def test_host_allowed(host_header, bound, ok):
    assert sec.host_allowed(host_header, bound) is ok


def test_host_allowed_wildcard_bind_needs_declared_hosts():
    # A wildcard bind never equals a client Host, so only loopback passes by default...
    assert sec.host_allowed("mc.internal:7777", "0.0.0.0") is False
    assert sec.host_allowed("127.0.0.1:7777", "0.0.0.0") is True
    # ...unless the operator declares the real hostnames (MONEY_CENTER_ALLOWED_HOSTS).
    assert sec.host_allowed("mc.internal:7777", "0.0.0.0", ["mc.internal"]) is True
    assert sec.host_allowed("other.host:7777", "0.0.0.0", ["mc.internal"]) is False


def test_admin_token_reads_env(monkeypatch):
    monkeypatch.delenv("MONEY_CENTER_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert sec.admin_token() == ""
    monkeypatch.setenv("ADMIN_TOKEN", "  fallback  ")
    assert sec.admin_token() == "fallback"
    monkeypatch.setenv("MONEY_CENTER_TOKEN", "primary")
    assert sec.admin_token() == "primary"   # MONEY_CENTER_TOKEN wins
