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


# --- truthful availability reporting (Phase 9 defect 2) ----------------------
# The governed browser package is present in App B's source but Playwright is NOT in
# App B's requirements, so every call raises BrowserUnavailable at runtime. That is the
# INTENDED architecture, not an omission: root requirements.txt:20 records
# "playwright — local only (browser automation)", and the dependency is declared only in
# requirements-kdp.txt, a separate worker image.
#
# Installing a browser into the production web process would put an automation engine and
# its download surface inside the public API service, which is exactly the coupling the
# split avoids. So the capability is reported UNAVAILABLE with an exact reason instead.
#
# This matters for the panel: a dashboard must never infer READY from the code being
# importable. It reports what a real dependency probe returned.

#: Where browser automation is meant to run.
BROWSER_INTENDED_RUNTIME = "local connector / kdp worker image (never the App B web process)"


def browser_availability() -> dict:
    """Probe Playwright and report truthfully, with the exact dependency reason."""
    try:
        import playwright  # noqa: F401
    except Exception as exc:
        return {
            "state": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {exc}",
            "missing_dependency": "playwright",
            "declared_in": "requirements-kdp.txt (worker image); root requirements.txt "
                           "marks it 'local only'",
            "absent_from": "backend/requirements.txt (App B web process) - by design",
            "intended_runtime": BROWSER_INTENDED_RUNTIME,
        }
    return {
        "state": "AVAILABLE",
        "reason": "playwright import succeeded",
        "intended_runtime": BROWSER_INTENDED_RUNTIME,
    }
