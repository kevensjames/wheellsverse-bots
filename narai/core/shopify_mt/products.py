"""
Multi-tenant product pipeline.

Same draft → 4 angled 3D images → quality gate → activate flow used for
your own store, but scoped to any merchant's shop domain + token.

Usage:
    from narai.core.shopify_mt.products import create_product_for_merchant
    result = create_product_for_merchant(merchant_id, ProductBrief(...))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from core.cover_engine import generate_cover
from narai.core.shopify_mt import db as mt_db
from narai.core.shopify_mt.client import ShopifyAdminClient, ShopifyAPIError

log = logging.getLogger("shopify_mt.products")

MIN_IMAGES = 4
MIN_DESC_CHARS = 300
MIN_TAGS = 3

# Same 3D angles as the single-tenant engine — consistency across stores.
IMAGE_ANGLES = [
    ("hero", "hero product shot, centered composition, studio lighting, clean dark gradient background, 3D render, octane, 8k, photorealistic"),
    ("lifestyle", "lifestyle context shot, cinematic environment, moody atmosphere, depth of field, 3D render, unreal engine quality, 4k"),
    ("detail", "extreme close-up detail shot, macro photography style, premium texture focus, dramatic rim lighting, 3D render, photorealistic"),
    ("flatlay", "top-down flat-lay composition, editorial magazine style, negative space, minimalist dark surface, 3D render, studio grade"),
]


@dataclass
class ProductBrief:
    """Everything needed to create a product on a merchant's store."""
    title: str
    body_html: str
    price: float
    tags: str
    product_type: str
    base_image_concept: str
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    vendor: str = "NarAI"
    requires_shipping: bool = False
    printify_enabled: bool = False
    metadata: dict = field(default_factory=dict)


class QualityGateFailed(Exception):
    pass


class InsufficientImages(Exception):
    pass


def _generate_image_set(base_concept: str, title: str, product_type: str) -> list[str]:
    """Return the hosted URLs of the generated images (max 4)."""
    urls = []
    for angle_name, angle_style in IMAGE_ANGLES[:MIN_IMAGES]:
        result = generate_cover(
            {"dalle": f"{base_concept}, {angle_style}"},
            "shopify",
            f"{title}_{angle_name}",
            product_type,
        )
        if result.get("success") and result.get("url"):
            urls.append(result["url"])
        else:
            log.warning(f"[shopify_mt.products] image '{angle_name}' failed: {result.get('error')}")
    return urls


def _run_quality_gate(product: dict) -> None:
    errors = []
    if len(product.get("images") or []) < MIN_IMAGES:
        errors.append(f"< {MIN_IMAGES} images")
    body = product.get("body_html") or ""
    if len(body) < MIN_DESC_CHARS:
        errors.append(f"desc < {MIN_DESC_CHARS} chars (got {len(body)})")
    tags = [t.strip() for t in (product.get("tags") or "").split(",") if t.strip()]
    if len(tags) < MIN_TAGS:
        errors.append(f"< {MIN_TAGS} tags")
    variants = product.get("variants") or []
    if not variants or float(variants[0].get("price", 0) or 0) <= 0:
        errors.append("price <= 0")
    if not product.get("title"):
        errors.append("missing title")
    if errors:
        raise QualityGateFailed("; ".join(errors))


def create_product_for_merchant(merchant_id: str, brief: ProductBrief) -> dict:
    """
    Create a product on a merchant's Shopify store. Draft-first, 4+ images, gated.

    Returns a dict with {success, product_id, error, status}.
    Raises nothing — catches everything and logs to merchant_events.
    """
    merchant = mt_db.get_merchant_by_id(merchant_id)
    if not merchant:
        return {"success": False, "error": "merchant not found"}
    if merchant.get("uninstalled_at"):
        return {"success": False, "error": "merchant uninstalled"}

    token = mt_db.get_decrypted_token(merchant)
    client = ShopifyAdminClient(merchant["shop_domain"], token)
    product_id: Optional[int] = None

    try:
        # 1. Create as DRAFT
        created = client.create_product({
            "title": brief.title,
            "body_html": brief.body_html,
            "vendor": brief.vendor,
            "product_type": brief.product_type,
            "tags": brief.tags,
            "status": "draft",
            "variants": [{
                "price": str(brief.price),
                "requires_shipping": brief.requires_shipping,
                "taxable": True,
                "fulfillment_service": "manual",
            }],
        })
        product_id = created.get("id")
        if not product_id:
            return {"success": False, "error": "product create returned no id"}

        # 2. Generate + attach 4 angled 3D images — hard-required
        image_urls = _generate_image_set(
            brief.base_image_concept, brief.title, brief.product_type
        )
        if len(image_urls) < MIN_IMAGES:
            client.delete_product(product_id)
            err = f"only {len(image_urls)}/{MIN_IMAGES} images generated — draft deleted"
            mt_db.log_event(merchant_id, "product.create", {
                "brief": brief.title, "error": err
            }, severity="error")
            return {"success": False, "error": err}

        for idx, url in enumerate(image_urls):
            try:
                client.attach_image(product_id, url, f"{brief.title} — angle {idx+1}", idx + 1)
            except ShopifyAPIError as e:
                log.warning(f"[shopify_mt.products] image {idx+1} upload failed: {e}")

        # 3. Quality gate — fetch fresh product state
        fresh = client.get_product(product_id)
        _run_quality_gate(fresh)

        # 4. Activate
        activated = client.update_product(product_id, {"status": "active"})

        # 5. Record in our DB
        mt_db.save_merchant_product(
            merchant_id=merchant_id,
            shopify_product_id=product_id,
            title=brief.title,
            source="dalle",
            images_count=len(image_urls),
            quality_gate_passed=True,
            published=True,
            price_cents=int(brief.price * 100),
            shopify_handle=activated.get("handle"),
        )
        mt_db.log_event(merchant_id, "product.create", {
            "product_id": product_id,
            "title": brief.title,
            "images": len(image_urls),
        })
        return {
            "success": True,
            "product_id": product_id,
            "handle": activated.get("handle"),
            "status": "active",
            "images_count": len(image_urls),
        }

    except QualityGateFailed as e:
        mt_db.log_event(merchant_id, "product.gate_failed", {
            "product_id": product_id, "reason": str(e),
        }, severity="warn")
        if product_id:
            mt_db.save_merchant_product(
                merchant_id=merchant_id, shopify_product_id=product_id,
                title=brief.title, source="dalle",
                images_count=0, quality_gate_passed=False, published=False,
                price_cents=int(brief.price * 100),
            )
        return {"success": False, "product_id": product_id, "error": f"gate: {e}", "status": "draft"}

    except ShopifyAPIError as e:
        mt_db.log_event(merchant_id, "product.shopify_error", {
            "error": e.message, "status": e.status,
        }, severity="error")
        return {"success": False, "error": f"shopify: {e}"}

    except Exception as e:
        log.exception(f"[shopify_mt.products] unexpected error for merchant {merchant_id}")
        mt_db.log_event(merchant_id, "product.error", {
            "error": f"{type(e).__name__}: {e}"
        }, severity="error")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
