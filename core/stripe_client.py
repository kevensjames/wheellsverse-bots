#!/usr/bin/env python3
"""
core/stripe_client.py
─────────────────────────────────────────────────────────────────────────────
Stripe payment integration.

Features:
  - Payment links (no-code checkout for bot packs, coaching, products)
  - Invoice creation + sending (wired to bot #69)
  - Customer management
  - Webhook event handling (payment success → trigger drip enroll)

Credentials needed in .env:
  STRIPE_SECRET_KEY        — sk_live_... or sk_test_...
  STRIPE_WEBHOOK_SECRET    — whsec_... (from Stripe Dashboard → Webhooks)
  STRIPE_PUBLISHABLE_KEY   — pk_live_... (for frontend, optional)

Products to pre-create (run once: python -m core.stripe_client setup):
  - WheellsVerse Bot Pack  ($97 one-time)
  - WheellsVerse Pro       ($29/mo subscription)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("stripe_client")

STRIPE_DATA_FILE = ROOT / "data" / "stripe_products.json"


class StripeClient:

    def __init__(self):
        self.secret_key = os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        self.publishable_key = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

    def _stripe(self):
        if not self.secret_key:
            raise RuntimeError(
                "STRIPE_SECRET_KEY not set in .env. "
                "Get it from dashboard.stripe.com → Developers → API keys"
            )
        import stripe
        stripe.api_key = self.secret_key
        return stripe

    # ── Products & Prices ─────────────────────────────────────────────────────

    def create_product(self, name: str, description: str = "") -> Dict:
        s = self._stripe()
        product = s.Product.create(name=name, description=description)
        logger.info(f"Product created: {product.id} — {name}")
        return {"id": product.id, "name": product.name}

    def create_price(self, product_id: str, amount_cents: int,
                     currency: str = "usd",
                     recurring: bool = False,
                     interval: str = "month") -> Dict:
        s = self._stripe()
        kwargs: Dict = {
            "product": product_id,
            "unit_amount": amount_cents,
            "currency": currency,
        }
        if recurring:
            kwargs["recurring"] = {"interval": interval}
        price = s.Price.create(**kwargs)
        logger.info(f"Price created: {price.id} — ${amount_cents / 100:.2f}")
        return {"id": price.id, "amount": amount_cents, "currency": currency}

    def setup_default_products(self) -> Dict:
        """Create WheellsVerse products on first run. Idempotent."""
        self._stripe()
        # Check if already created
        existing = {}
        if STRIPE_DATA_FILE.exists():
            try:
                existing = json.loads(STRIPE_DATA_FILE.read_text())
            except Exception:
                pass

        if existing.get("bot_pack_price_id"):
            logger.info("Stripe products already set up")
            return existing

        # Bot Pack — one-time $97
        pack = self.create_product(
            "WheellsVerse Bot Pack",
            "Access to all 83 AI automation bots + setup guide"
        )
        pack_price = self.create_price(pack["id"], 9700)  # $97.00

        # Pro subscription — $29/mo
        pro = self.create_product(
            "WheellsVerse Pro",
            "Monthly access: new bots, priority support, weekly strategy calls"
        )
        pro_price = self.create_price(pro["id"], 2900, recurring=True)

        data = {
            "bot_pack_product_id": pack["id"],
            "bot_pack_price_id": pack_price["id"],
            "pro_product_id": pro["id"],
            "pro_price_id": pro_price["id"],
        }
        STRIPE_DATA_FILE.parent.mkdir(exist_ok=True)
        STRIPE_DATA_FILE.write_text(json.dumps(data, indent=2))
        logger.info("Stripe products created and saved")
        return data

    # ── Payment Links ─────────────────────────────────────────────────────────

    def create_payment_link(self, price_id: str,
                            quantity: int = 1,
                            success_url: str = "") -> Dict:
        s = self._stripe()
        kwargs: Dict = {
            "line_items": [{"price": price_id, "quantity": quantity}],
        }
        if success_url:
            kwargs["after_completion"] = {
                "type": "redirect",
                "redirect": {"url": success_url},
            }
        link = s.PaymentLink.create(**kwargs)
        logger.info(f"Payment link created: {link.url}")
        return {"id": link.id, "url": link.url}

    def get_checkout_links(self) -> Dict[str, str]:
        """Return ready-to-use payment URLs for both products."""
        data = {}
        if STRIPE_DATA_FILE.exists():
            try:
                data = json.loads(STRIPE_DATA_FILE.read_text())
            except Exception:
                pass

        site = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev")
        links = {}

        if data.get("bot_pack_price_id"):
            try:
                lnk = self.create_payment_link(
                    data["bot_pack_price_id"],
                    success_url=f"{site}?purchase=bot_pack",
                )
                links["bot_pack"] = lnk["url"]
            except Exception as e:
                logger.warning(f"Could not create bot_pack link: {e}")

        if data.get("pro_price_id"):
            try:
                lnk = self.create_payment_link(
                    data["pro_price_id"],
                    success_url=f"{site}?purchase=pro",
                )
                links["pro"] = lnk["url"]
            except Exception as e:
                logger.warning(f"Could not create pro link: {e}")

        return links

    # ── Invoices ──────────────────────────────────────────────────────────────

    def create_customer(self, email: str, name: str = "") -> Dict:
        s = self._stripe()
        customer = s.Customer.create(email=email, name=name or email)
        logger.info(f"Customer created: {customer.id} — {email}")
        return {"id": customer.id, "email": email}

    def create_invoice(self, customer_email: str, items: List[Dict],
                       send: bool = True) -> Dict:
        """
        Create and optionally send an invoice.

        items: [{"description": "...", "amount_cents": 5000, "quantity": 1}]
        """
        s = self._stripe()

        # Find or create customer
        existing = s.Customer.list(email=customer_email, limit=1)
        if existing.data:
            customer_id = existing.data[0].id
        else:
            customer_id = self.create_customer(customer_email)["id"]

        # Add invoice items
        for item in items:
            s.InvoiceItem.create(
                customer=customer_id,
                amount=item["amount_cents"],
                currency="usd",
                description=item["description"],
                quantity=item.get("quantity", 1),
            )

        # Create invoice
        invoice = s.Invoice.create(customer=customer_id, auto_advance=True)

        result = {
            "invoice_id": invoice.id,
            "customer_id": customer_id,
            "amount": invoice.amount_due,
            "status": invoice.status,
            "url": invoice.hosted_invoice_url or "",
        }

        if send:
            try:
                invoice.send_invoice()
                result["sent"] = True
                logger.info(f"Invoice {invoice.id} sent to {customer_email}")
            except Exception as e:
                result["sent"] = False
                result["send_error"] = str(e)

        return result

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def handle_webhook(self, payload: bytes, sig_header: str) -> Dict:
        """
        Verify + handle a Stripe webhook event.
        Call this from POST /api/stripe/webhook.
        """
        s = self._stripe()
        try:
            event = s.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except Exception as e:
            raise ValueError(f"Webhook verification failed: {e}")

        event_type = event["type"]
        logger.info(f"Stripe webhook: {event_type}")

        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            customer_email = session.get("customer_details", {}).get("email", "")
            if customer_email:
                # Auto-enroll buyer in drip
                try:
                    from core.drip import enroll_in_drip
                    enroll_in_drip(email=customer_email, source="stripe_purchase")
                    logger.info(f"Post-purchase drip enrolled: {customer_email}")
                except Exception as e:
                    logger.warning(f"Post-purchase drip failed: {e}")

        elif event_type == "invoice.payment_succeeded":
            inv = event["data"]["object"]
            amount_cents = inv.get("amount_paid", 0)
            customer_email = inv.get("customer_email", "")
            logger.info(f"Payment succeeded: invoice {inv['id']} — ${amount_cents / 100:.2f}")
            try:
                from core.telegram import notify_payment
                notify_payment(amount_cents=amount_cents, customer_email=customer_email)
            except Exception:
                pass

        return {"received": True, "event": event_type}

    # ── Status ────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return bool(self.secret_key)

    def get_status(self) -> Dict:
        if not self.is_connected():
            return {"connected": False, "reason": "STRIPE_SECRET_KEY not set"}
        try:
            s = self._stripe()
            # stripe SDK v7+ changed Account.retrieve() — use a lightweight list call instead
            try:
                account = s.Account.retrieve()
                account_id = account.id
                country = account.get("country", "") if hasattr(account, "get") else getattr(account, "country", "")
            except Exception:
                # Fallback: just verify the key works by listing 1 product
                s.Product.list(limit=1)
                account_id = "verified"
                country = ""
            return {
                "connected": True,
                "account_id": account_id,
                "mode": "live" if "live" in self.secret_key else "test",
                "country": country,
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}


_client: Optional[StripeClient] = None


def get_stripe() -> StripeClient:
    global _client
    if _client is None:
        _client = StripeClient()
    return _client


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        client = get_stripe()
        result = client.setup_default_products()
        print(json.dumps(result, indent=2))
    else:
        client = get_stripe()
        print(json.dumps(client.get_status(), indent=2))
