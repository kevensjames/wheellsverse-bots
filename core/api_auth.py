#!/usr/bin/env python3
"""
core/api_auth.py
─────────────────────────────────────────────────────────────────────────────
Deny-by-default authorization decisions for the shared Core API middleware.

Framework-independent (no FastAPI import) so the routing decision is unit-testable
without importing the 633 KB core/api.py app.

Background: the 2026-07-12 audit found ~40 STATE-CHANGING operator-control routes
reachable with no API key, because they were placed under blanket public prefixes
AND hand-added to the public-path allowlist (e.g. /api/factory/reset wipes state,
/api/shopify/discount mints discount codes, product CRUD, autopilot start/stop).

This module force-requires the operator key on those mutating routes, overriding
their (wrong) public status, while leaving every read endpoint and every genuinely
public route (webhooks, login, OAuth, signed downloads, self-authing /api/nx/*)
exactly as it was — the smallest change that closes the hole without breaking a
legitimately public route.
─────────────────────────────────────────────────────────────────────────────
"""

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Exact operator-control routes that change state and must require the API key.
_LOCKED_EXACT = frozenset({
    # Product factory control
    "/api/factory/start", "/api/factory/stop", "/api/factory/reset",
    # NarAI autopilot
    "/api/narai-autopilot/start", "/api/narai-autopilot/stop", "/api/narai-autopilot/reels",
    # Shopify autopilot
    "/api/shopify-autopilot/start", "/api/shopify-autopilot/stop",
    "/api/shopify-autopilot/trend-scan",
    # Shopify agent workforce
    "/api/shopify/agents/start", "/api/shopify/agents/stop",
    "/api/shopify/agents/dispatch", "/api/shopify/agents/upgrade-now",
    # Shopify media / intelligence
    "/api/shopify/media/generate-batch",
    "/api/shopify/intelligence/analyze", "/api/shopify/intelligence/autopilot",
    # Shopify store mutations
    "/api/shopify/products", "/api/shopify/publish-narai-product",
    "/api/shopify/discount", "/api/shopify/register-webhooks",
    # Standalone-agents / boutique
    "/api/sa/start", "/api/sa/stop", "/api/sa/trend-scan", "/api/sa/setup-boutique",
    # Bot runners / revenue writes
    "/api/narai/run_bot", "/api/narai/run", "/api/narai/revenue",
    # QC action
    "/api/qc/review",
})

# Locked routes that carry a path parameter (matched by prefix).
_LOCKED_PREFIXES = (
    "/api/shopify/products/",        # PUT/DELETE /api/shopify/products/{id}
    "/api/shopify/media/generate/",  # POST /api/shopify/media/generate/{product_id}
    "/api/narai/schedules/",         # PATCH /{id}, POST /{id}/trigger
    "/api/narai-autopilot/queue/",   # POST /{idx}/mark_done
)


def is_locked_mutation(path: str, method: str) -> bool:
    """True if `path` is an operator-control route being invoked with a state-
    changing method — these must require the API key regardless of any public
    allowlist entry. Reads (GET/HEAD/OPTIONS) are never locked here."""
    if (method or "").upper() in _SAFE_METHODS:
        return False
    return path in _LOCKED_EXACT or any(path.startswith(p) for p in _LOCKED_PREFIXES)


def requires_api_key(path: str, method: str, is_public_by_existing_rules: bool) -> bool:
    """Should the Core API middleware demand the operator key for this request?

    - Non-/api/ paths: no (handled elsewhere).
    - A locked mutating operator route: YES, even if the legacy allowlist marked it
      public (that mislabelling is the bug).
    - Otherwise: the existing rule — public routes stay public, everything else
      under /api/ requires the key (unchanged behavior).
    """
    if not path.startswith("/api/"):
        return False
    if is_locked_mutation(path, method):
        return True
    return not is_public_by_existing_rules
