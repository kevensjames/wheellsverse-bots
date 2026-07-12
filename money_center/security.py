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
import os
import secrets

# Hosts that mean "this machine only". A non-loopback bind exposes the dashboard
# (and therefore arbitrary command execution) to the network.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def is_loopback(host: str) -> bool:
    """True if `host` binds only the local machine."""
    h = (host or "").strip().lower()
    return h in _LOOPBACK_HOSTS or h.startswith("127.")


def _hostname(host_header: str) -> str:
    """Extract the bare hostname from a Host header value (strip port / IPv6 brackets)."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):                      # [ipv6] or [ipv6]:port
        return h[1:h.index("]")] if "]" in h else h.strip("[]")
    if h.count(":") == 1 and h.rsplit(":", 1)[1].isdigit():
        return h.rsplit(":", 1)[0]             # host:port
    return h


def host_allowed(host_header: str, bound_host: str) -> bool:
    """Reject a request whose Host header is neither loopback nor the configured
    bind host. This defeats DNS-rebinding, where a malicious page rebinds its own
    domain to 127.0.0.1 to reach the loopback dashboard with a foreign Host."""
    name = _hostname(host_header)
    if is_loopback(name):
        return True
    return bool(name) and name == _hostname(bound_host)


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
