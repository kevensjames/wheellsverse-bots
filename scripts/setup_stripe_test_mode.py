#!/usr/bin/env python3
"""Idempotently create the Stripe test-mode mirror for the Telegram private-group subscription.

Usage:
    STRIPE_TEST_KEY=sk_test_… python3 scripts/setup_stripe_test_mode.py

Creates (or reuses if names match):
  • Test product:  "WheellsVerse Insider — Private Telegram Group (TEST)"
  • Test price:    $19.00/mo USD recurring
  • Test webhook:  same URL as prod, but only test-mode events route here

Writes a .env.test fragment to stdout — paste it into Railway as test-env vars
or into a local `.env.test` file you `source` before running the local server.

Why a separate test webhook? Stripe sends test events with `livemode=false`
to the *test endpoint you registered with the test key*. Live events go to
your live endpoint. They never cross over. Reusing one URL is fine; the
signing secrets are different.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    key = os.environ.get("STRIPE_TEST_KEY", "").strip()
    if not key.startswith("sk_test_"):
        sys.stderr.write(
            "STRIPE_TEST_KEY env var must be set and start with sk_test_…\n"
        )
        return 1

    try:
        import stripe
    except ImportError:
        sys.stderr.write("Run: pip install stripe\n")
        return 1

    stripe.api_key = key

    product_name = "WheellsVerse Insider — Private Telegram Group (TEST)"

    # Idempotent product
    product = None
    for p in stripe.Product.list(limit=100, active=True).auto_paging_iter():
        if p.name == product_name:
            product = p
            break
    if product is None:
        product = stripe.Product.create(
            name=product_name,
            description="TEST mirror of the live private TG group subscription.",
            metadata={"product": "tg_group", "mode": "test"},
        )
        print(f"created product: {product.id}", file=sys.stderr)
    else:
        print(f"reusing product:  {product.id}", file=sys.stderr)

    # Idempotent price ($19/mo)
    price = None
    for pr in stripe.Price.list(product=product.id, active=True, limit=100).auto_paging_iter():
        rec = pr.recurring or {}
        if (pr.unit_amount == 1900 and pr.currency == "usd"
                and rec.get("interval") == "month"):
            price = pr
            break
    if price is None:
        price = stripe.Price.create(
            product=product.id,
            unit_amount=1900,
            currency="usd",
            recurring={"interval": "month"},
            metadata={"product": "tg_group", "mode": "test"},
        )
        print(f"created price:    {price.id}", file=sys.stderr)
    else:
        print(f"reusing price:    {price.id}", file=sys.stderr)

    # Idempotent webhook
    webhook_url = os.environ.get(
        "WEBHOOK_URL", "https://app.wheellsverse.com/api/stripe/webhook"
    )
    webhook = None
    for w in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter():
        if w.url == webhook_url:
            webhook = w
            break

    if webhook is None:
        webhook = stripe.WebhookEndpoint.create(
            url=webhook_url,
            enabled_events=[
                "checkout.session.completed",
                "customer.subscription.updated",
                "customer.subscription.deleted",
                "invoice.paid",
            ],
            description="WheellsVerse — test webhook (TG subscription)",
            metadata={"created_by": "setup_stripe_test_mode", "mode": "test"},
        )
        whsec = webhook.secret  # only present on creation
        print(f"created webhook:  {webhook.id}", file=sys.stderr)
    else:
        whsec = "<existing — rotate via dashboard if you need it>"
        print(f"reusing webhook:  {webhook.id}", file=sys.stderr)

    # Print env block to stdout so the user can capture/paste/redirect
    print()
    print("# ---- paste into Railway (test environment) or .env.test ----")
    print(f"STRIPE_SECRET_KEY={key}")
    print(f"STRIPE_PRICE_TG_GROUP={price.id}")
    print(f"STRIPE_WEBHOOK_SECRET={whsec}")
    print()
    print("# Test card for end-to-end testing: 4242 4242 4242 4242 (any future date / any CVC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
