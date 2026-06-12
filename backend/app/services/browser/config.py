"""Browser policy — the security-critical core of KAI's computer-control
feature. PURE (no Playwright, no I/O) so it's 100% unit-testable.

Every navigation request must pass `check_url()`, which enforces, in order:
  1. kill-switch     — KAI_BROWSER_ENABLED must be truthy, else nothing runs
  2. scheme          — only http/https (blocks file:, javascript:, data:, about:)
  3. SSRF guard      — blocks localhost, private/loopback/link-local/reserved IPs
                       (incl. the cloud metadata IP 169.254.169.254)
  4. allowlist       — host must match an allowlisted domain; the allowlist is
                       config-driven and DEFAULT EMPTY → nothing is navigable

Envelope (v1, operator-chosen): read + propose. Reads (navigate/extract) are
allowed within the allowlist; write actions (click/type/submit) are PROPOSED,
never executed. So nothing here authorizes a state change.

Known v1 limitation: allowlist matching is by hostname suffix and IP-literals
are blocked, but we do NOT resolve DNS, so a DNS-rebinding allowlisted domain
pointing at a private IP is not caught. Acceptable for an operator-curated
allowlist of public read-only sites; revisit if the envelope widens.
"""
from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlsplit

# Matches a leading "scheme:" (http:, https:, file:, javascript:, data:, …).
# Used to tell a real scheme from a bare host so we only default-prepend
# https:// to scheme-less input (and never mask a dangerous scheme).
_HAS_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

# Defaults are conservative; every value is env-overridable.
DEFAULT_PAGE_TIMEOUT_MS = 15_000   # page load
DEFAULT_ACTION_TIMEOUT_MS = 5_000  # per-action
MAX_TEXT_CHARS = 8_000             # cap extracted text returned to the LLM


class BrowserPolicyError(Exception):
    """A navigation request violated policy (disabled / bad scheme / SSRF /
    not allowlisted). The reason string is safe to surface to the operator."""


def _is_env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def browser_enabled() -> bool:
    """Master kill-switch. Default OFF — the tool isn't even registered unless
    this is explicitly set. Mirrors the handoff's KAI_BROWSER_ENABLED=0 default."""
    return _is_env_truthy("KAI_BROWSER_ENABLED")


# Envelope B: actions KAI may execute (operator-approved). Deliberately narrow —
# no file uploads, downloads, navigation-by-script, or JS eval.
WRITE_ACTION_TYPES = ("click", "type", "submit", "select")


def write_enabled() -> bool:
    """SECOND kill-switch, default OFF — gates WRITE execution specifically.
    Even with the browser enabled, executing clicks/types/submits requires this
    deliberate extra opt-in (KAI_BROWSER_WRITE_ENABLED=1). Reads are unaffected."""
    return _is_env_truthy("KAI_BROWSER_WRITE_ENABLED")


def headless() -> bool:
    """Headless by default; KAI_BROWSER_HEADED=1 to watch (debugging only)."""
    return not _is_env_truthy("KAI_BROWSER_HEADED")


def page_timeout_ms() -> int:
    return _int_env("KAI_BROWSER_PAGE_TIMEOUT_MS", DEFAULT_PAGE_TIMEOUT_MS)


def action_timeout_ms() -> int:
    return _int_env("KAI_BROWSER_ACTION_TIMEOUT_MS", DEFAULT_ACTION_TIMEOUT_MS)


def allowlist() -> list[str]:
    """Parsed KAI_BROWSER_ALLOWLIST (comma-separated registrable domains).
    Empty/unset → [] → nothing is navigable."""
    raw = os.environ.get("KAI_BROWSER_ALLOWLIST", "")
    return [d.strip().lower().lstrip(".") for d in raw.split(",") if d.strip()]


def host_allowed(host: str, allow: list[str] | None = None) -> bool:
    """True if host equals an allowlisted domain or is a subdomain of one."""
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    allow = allowlist() if allow is None else allow
    for entry in allow:
        if host == entry or host.endswith("." + entry):
            return True
    return False


def _is_blocked_ip(host: str) -> bool:
    """True if host is an IP literal in a private/loopback/link-local/reserved
    range (SSRF guard). Non-IP hostnames return False here (allowlist handles them)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def check_url(url: str, *, allow: list[str] | None = None) -> str:
    """Validate a navigation target against the full policy. Returns the
    normalized URL on success; raises BrowserPolicyError otherwise.

    Order matters: kill-switch → scheme → SSRF → allowlist. Each failure has a
    distinct, operator-safe reason.
    """
    if not browser_enabled():
        raise BrowserPolicyError(
            "browser is disabled (set KAI_BROWSER_ENABLED=1 to enable)"
        )
    url = (url or "").strip()
    if not url:
        raise BrowserPolicyError("empty url")

    # Operator convenience: a bare host like "example.com" or
    # "example.com/path" has no scheme, which urlsplit can't host-parse. Default
    # it to https. We ONLY prepend when there's no leading "scheme:" at all — so
    # javascript:/file:/data: keep their scheme and get rejected below, never
    # masked into an https URL.
    if not _HAS_SCHEME_RE.match(url):
        url = "https://" + url

    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise BrowserPolicyError(
            f"scheme {scheme or '(none)'!r} not allowed — only http/https"
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise BrowserPolicyError("url has no host")
    if host == "localhost" or host.endswith(".localhost"):
        raise BrowserPolicyError("localhost is blocked (SSRF guard)")
    if _is_blocked_ip(host):
        raise BrowserPolicyError(f"private/loopback IP {host} is blocked (SSRF guard)")

    if not host_allowed(host, allow):
        allow_list = allowlist() if allow is None else allow
        hint = (
            "allowlist is empty — add domains to KAI_BROWSER_ALLOWLIST"
            if not allow_list
            else f"allowed: {', '.join(allow_list)}"
        )
        raise BrowserPolicyError(f"{host} is not allowlisted ({hint})")

    return url


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
