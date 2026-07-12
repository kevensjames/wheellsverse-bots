#!/usr/bin/env python3
"""
money_center/security.py
─────────────────────────────────────────────────────────────────────────────
Pure (framework-independent) security helpers for the Money Center dashboard.

The dashboard can launch arbitrary shell commands, so these guards decide who
may reach it and protect its state-changing routes. They are deliberately free
of any Flask import so they can be unit-tested without the web stack installed.
─────────────────────────────────────────────────────────────────────────────
"""

import hmac
import ipaddress
import os
import secrets


def is_loopback(host: str) -> bool:
    """True only if `host` is the 'localhost' name or a loopback IP LITERAL
    (127.0.0.0/8 or ::1). Parsed with ipaddress so a DNS name that merely starts
    with '127.' (e.g. an attacker's '127.evil.com') is NOT treated as loopback."""
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _hostname(host_header: str) -> str:
    """Extract the bare hostname from a Host header value (strip port / IPv6 brackets)."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):                      # [ipv6] or [ipv6]:port
        return h[1:h.index("]")] if "]" in h else h.strip("[]")
    if h.count(":") == 1 and h.rsplit(":", 1)[1].isdigit():
        return h.rsplit(":", 1)[0]             # host:port
    return h


def allowed_hosts_config() -> list:
    """Operator-declared hostnames for a network-exposed (wildcard/proxied) bind,
    from MONEY_CENTER_ALLOWED_HOSTS (comma-separated)."""
    raw = os.environ.get("MONEY_CENTER_ALLOWED_HOSTS", "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def host_allowed(host_header: str, bound_host: str, extra_hosts=()) -> bool:
    """Reject a request whose Host header is neither loopback, the configured bind
    host, nor an operator-declared host. Defeats DNS-rebinding, where a malicious
    page rebinds its own domain to a loopback/bound address with a foreign Host.

    A wildcard bind (0.0.0.0 / ::) can never equal a client Host, so exposed
    deployments must declare their real hostnames via `extra_hosts`
    (MONEY_CENTER_ALLOWED_HOSTS); loopback is always accepted."""
    name = _hostname(host_header)
    if not name:
        return False
    if is_loopback(name):
        return True
    if name == _hostname(bound_host):
        return True
    return any(name == _hostname(h) for h in extra_hosts)


def admin_token() -> str:
    """The operator token required to sign in, from the environment ('' if unset)."""
    return (os.environ.get("MONEY_CENTER_TOKEN")
            or os.environ.get("ADMIN_TOKEN")
            or "").strip()


def network_bind_allowed(host: str, token: str) -> bool:
    """A shell-executing dashboard may bind a non-loopback host ONLY when an
    operator token is configured. Loopback is allowed with or without a token."""
    return is_loopback(host) or bool(token)


def token_valid(supplied: str, expected: str) -> bool:
    """Constant-time check of a submitted operator token. Empty either side fails."""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(supplied), str(expected))


def new_csrf_token() -> str:
    return secrets.token_hex(16)


def csrf_valid(supplied: str, expected: str) -> bool:
    """Constant-time CSRF token comparison. Empty either side fails."""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(supplied), str(expected))


def session_secret() -> str:
    """Signing key for the session cookie. Prefer a stable env value so sessions
    survive restarts; otherwise a fresh random key (operators re-auth on restart)."""
    return os.environ.get("MONEY_CENTER_SECRET") or secrets.token_hex(32)
