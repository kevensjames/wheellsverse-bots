"""KAI computer-control / browser-use (v1: read + propose).

The highest-risk feature in the roadmap, shipped with a deliberately narrow
envelope: KAI can navigate an operator-curated allowlist of domains and READ
(extract text/links, screenshot); it can PROPOSE write actions (click/type/
submit) but v1 NEVER executes them. Hardened by:
  - KAI_BROWSER_ENABLED kill-switch (default OFF — tool not registered)
  - KAI_SCOPE_BROWSER governance scope + audit log
  - domain allowlist (default empty) + SSRF guard + scheme allowlist
  - isolated ephemeral Playwright context (no profile/cookies), hard timeouts

  config   — the pure policy core (check_url) — security-critical, fully tested
  log      — append-only action log (data/browser/actions.jsonl)
  session  — the only place Playwright runs (worker thread, read-only)
"""
from app.services.browser.config import (  # noqa: F401
    MAX_TEXT_CHARS,
    WRITE_ACTION_TYPES,
    BrowserPolicyError,
    action_timeout_ms,
    allowlist,
    browser_enabled,
    check_url,
    headless,
    host_allowed,
    page_timeout_ms,
    write_enabled,
)
from app.services.browser.log import (  # noqa: F401
    BROWSER_LOG_PATH,
    BrowserAction,
    list_actions,
    record_action,
    stats,
)
from app.services.browser.session import (  # noqa: F401
    BrowserUnavailable,
    execute_actions,
    read_page,
    screenshot,
)

__all__ = [
    "MAX_TEXT_CHARS",
    "BrowserAction",
    "BrowserPolicyError",
    "BrowserUnavailable",
    "BROWSER_LOG_PATH",
    "action_timeout_ms",
    "allowlist",
    "browser_enabled",
    "check_url",
    "execute_actions",
    "headless",
    "host_allowed",
    "list_actions",
    "page_timeout_ms",
    "read_page",
    "record_action",
    "screenshot",
    "stats",
    "write_enabled",
    "WRITE_ACTION_TYPES",
]
