#!/usr/bin/env python3
"""
core/shopify_client.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Shopify Integration

Capabilities:
  • OAuth 2.0 install flow (authorize → callback → store token)
  • Products    — create, update, list, delete, add images
  • Digital files — attach downloadable files to products (digital products)
  • Orders      — list, read, fulfill
  • Customers   — list, read
  • Inventory   — read, adjust
  • Price rules — discounts and promo codes
  • Reports     — sales summary
  • Webhooks    — register + verify HMAC signatures
  • NarAI sync  — auto-publish NarAI digital products to Shopify

OAuth flow:
  1. GET  /api/shopify/oauth-url?shop=mystore.myshopify.com
  2. User approves on Shopify → redirected to:
     GET  /api/shopify/callback?code=...&shop=...&hmac=...
  3. Token stored in data/shopify_token.json
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("shopify_client")

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

TOKEN_FILE = DATA_DIR / "shopify_token.json"
LOG_FILE   = DATA_DIR / "shopify_log.json"

API_VERSION = "2026-04"   # matches your Shopify dashboard setting

SCOPES = (
    "read_orders,write_orders,"
    "read_products,write_products,"
    "read_customers,"
    "read_inventory,write_inventory,"
    "read_fulfillments,write_fulfillments,"
    "read_price_rules,write_price_rules,"
    "write_draft_orders,"
    "read_reports,"
    "read_files,write_files,"
    "read_locations"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add_log(msg: str, level: str = "INFO"):
    log.info(f"[Shopify] {msg}")
    try:
        logs = []
        if LOG_FILE.exists():
            logs = json.loads(LOG_FILE.read_text())
        logs.insert(0, {"ts": _now(), "level": level, "msg": msg})
        LOG_FILE.write_text(json.dumps(logs[:500]))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# TOKEN MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _load_token() -> dict:
    try:
        if TOKEN_FILE.exists():
            return json.loads(TOKEN_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_token(data: dict):
    TOKEN_FILE.write_text(json.dumps(data, indent=2))


def get_credentials() -> tuple[str, str, str]:
    """
    Return (shop_domain, access_token, api_key).
    Priority: env vars (direct token) → saved OAuth token file.
    """
    # Direct token from .env (custom app flow — no OAuth needed)
    env_shop  = os.getenv("SHOPIFY_STORE", "")
    env_token = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
    if env_shop and env_token:
        return env_shop, env_token, os.getenv("SHOPIFY_API_KEY", "")

    # Fallback: OAuth token saved to disk
    tok = _load_token()
    return (
        tok.get("shop", ""),
        tok.get("access_token", ""),
        os.getenv("SHOPIFY_API_KEY", ""),
    )


def is_connected() -> bool:
    shop, token, _ = get_credentials()
    return bool(shop and token)


# ══════════════════════════════════════════════════════════════════════════════
# OAUTH FLOW
# ══════════════════════════════════════════════════════════════════════════════

def get_oauth_url(shop: str, state: str = "") -> str:
    """
    Build the Shopify OAuth authorization URL.
    Redirect the user (browser) to this URL to start the install flow.
    """
    api_key    = os.getenv("SHOPIFY_API_KEY", "")
    base_url   = os.getenv("RAILWAY_PUBLIC_URL", "http://localhost:5050").rstrip("/")
    redirect   = f"{base_url}/api/shopify/callback"
    nonce      = state or str(int(time.time()))

    params = urllib.parse.urlencode({
        "client_id":    api_key,
        "scope":        SCOPES,
        "redirect_uri": redirect,
        "state":        nonce,
    })
    shop = shop.rstrip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    return f"https://{shop}/admin/oauth/authorize?{params}"


def exchange_code_for_token(shop: str, code: str) -> dict:
    """
    Exchange the OAuth code for a permanent access token.
    Called from the /api/shopify/callback endpoint.
    Returns {success, access_token, shop, scope} or {success:False, error}.
    """
    api_key    = os.getenv("SHOPIFY_API_KEY", "")
    api_secret = os.getenv("SHOPIFY_API_SECRET", "")

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    body = json.dumps({
        "client_id":     api_key,
        "client_secret": api_secret,
        "code":          code,
    }).encode()

    try:
        req = urllib.request.Request(
            f"https://{shop}/admin/oauth/access_token",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        token  = data.get("access_token", "")
        scope  = data.get("scope", "")

        if not token:
            return {"success": False, "error": f"No token in response: {data}"}

        _save_token({
            "shop":         shop,
            "access_token": token,
            "scope":        scope,
            "connected_at": _now(),
            "api_key":      api_key,
        })
        _add_log(f"✅ OAuth complete — connected to {shop}")
        return {"success": True, "access_token": token, "shop": shop, "scope": scope}

    except Exception as e:
        _add_log(f"OAuth exchange failed: {e}", "ERROR")
        return {"success": False, "error": str(e)}


def verify_webhook_hmac(data: bytes, hmac_header: str) -> bool:
    """Verify Shopify webhook HMAC signature."""
    secret = os.getenv("SHOPIFY_API_SECRET", "")
    digest = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, hmac_header)


# ══════════════════════════════════════════════════════════════════════════════
# BASE API CALL
# ══════════════════════════════════════════════════════════════════════════════

def _api(
    method: str,
    endpoint: str,
    body: Optional[dict] = None,
    shop: str = "",
    token: str = "",
) -> dict:
    """
    Make a Shopify Admin REST API call.
    Returns parsed JSON response or {error: ...}.
    """
    if not shop or not token:
        creds = _load_token()
        shop  = shop  or creds.get("shop", "")
        token = token or creds.get("access_token", "")

    if not shop or not token:
        return {"error": "Shopify not connected — complete OAuth first"}

    url = f"https://{shop}/admin/api/{API_VERSION}/{endpoint}"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode()[:500]
        log.warning(f"[Shopify] {method} {endpoint} → {e.code}: {body_txt}")
        return {"error": f"HTTP {e.code}: {body_txt}"}
    except Exception as e:
        log.warning(f"[Shopify] {method} {endpoint} → {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTS
# ══════════════════════════════════════════════════════════════════════════════

def create_product(
    title: str,
    description: str,
    price: float,
    product_type: str = "Digital",
    tags: list[str] = None,
    vendor: str = "WheellsVerse",
    requires_shipping: bool = False,   # False for digital products
    images: list[dict] = None,
) -> dict:
    """
    Create a Shopify product listing.
    For digital products: requires_shipping=False, fulfillment_service='manual'.

    Returns {success, product_id, product_url, handle, error}.
    """
    payload = {
        "product": {
            "title":        title,
            "body_html":    description,
            "vendor":       vendor,
            "product_type": product_type,
            "tags":         ", ".join(tags or []),
            "status":       "active",
            "variants": [{
                "price":               f"{price:.2f}",
                "requires_shipping":   requires_shipping,
                "fulfillment_service": "manual",
                "inventory_management": None,
                "inventory_policy":    "continue",   # never out of stock (digital)
            }],
        }
    }

    if images:
        payload["product"]["images"] = images

    result = _api("POST", "products.json", payload)
    if "error" in result:
        _add_log(f"Create product failed: {result['error']}", "ERROR")
        return {"success": False, "error": result["error"]}

    product = result.get("product", {})
    pid     = product.get("id")
    handle  = product.get("handle", "")
    shop, *_ = get_credentials()
    url     = f"https://{shop}/products/{handle}" if shop and handle else ""

    _add_log(f"✅ Product created: '{title}' (ID {pid}) @ ${price}")
    return {
        "success":    True,
        "product_id": pid,
        "product_url": url,
        "handle":     handle,
        "admin_url":  f"https://{shop}/admin/products/{pid}",
        "product":    product,
    }


def update_product(product_id: int, updates: dict) -> dict:
    """Update an existing product. `updates` maps to Shopify product fields."""
    result = _api("PUT", f"products/{product_id}.json", {"product": updates})
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True, "product": result.get("product", {})}


def list_products(limit: int = 50, status: str = "active") -> list:
    """List products from the store."""
    result = _api("GET", f"products.json?limit={limit}&status={status}")
    return result.get("products", [])


def delete_product(product_id: int) -> dict:
    """Delete a product by ID."""
    result = _api("DELETE", f"products/{product_id}.json")
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True}


def add_product_image(product_id: int, image_url: str = "", image_path: str = "") -> dict:
    """
    Add a cover image to an existing product.
    Pass either image_url (hosted URL) or image_path (local file → base64).
    """
    if image_url:
        payload = {"image": {"src": image_url}}
    elif image_path and Path(image_path).exists():
        import base64
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
        payload = {"image": {"attachment": encoded, "filename": Path(image_path).name}}
    else:
        return {"success": False, "error": "No image_url or valid image_path provided"}

    result = _api("POST", f"products/{product_id}/images.json", payload)
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True, "image": result.get("image", {})}


# ══════════════════════════════════════════════════════════════════════════════
# DIGITAL FILES
# ══════════════════════════════════════════════════════════════════════════════

def upload_digital_file(file_path: str, filename: str = "") -> dict:
    """
    Upload a file to Shopify Files (used for digital product downloads).
    Returns {success, file_url, file_id}.

    Note: Shopify Files API uses GraphQL. Requires write_files scope.
    """
    import base64

    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    fname    = filename or path.name
    encoded  = base64.b64encode(path.read_bytes()).decode()
    mime     = "application/pdf" if fname.endswith(".pdf") else "application/octet-stream"

    shop, token, _ = get_credentials()
    if not shop or not token:
        return {"success": False, "error": "Shopify not connected"}

    # GraphQL mutation to create a staged upload
    gql_url = f"https://{shop}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    # Stage the upload
    stage_query = {
        "query": """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url parameters { name value } resourceUrl }
            userErrors { field message }
          }
        }
        """,
        "variables": {
            "input": [{
                "filename":   fname,
                "mimeType":   mime,
                "resource":   "FILE",
                "fileSize":   str(path.stat().st_size),
                "httpMethod": "POST",
            }]
        }
    }

    try:
        req = urllib.request.Request(
            gql_url,
            data=json.dumps(stage_query).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            stage_data = json.loads(r.read())

        targets = (
            stage_data.get("data", {})
            .get("stagedUploadsCreate", {})
            .get("stagedTargets", [])
        )
        if not targets:
            return {"success": False, "error": f"Stage failed: {stage_data}"}

        target      = targets[0]
        upload_url  = target["url"]
        params      = {p["name"]: p["value"] for p in target["parameters"]}
        resource_url = target["resourceUrl"]

        # Upload the actual file
        import io
        boundary = "----WheellsVerseBoundary"
        body_parts = []
        for key, val in params.items():
            body_parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}".encode()
            )
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{fname}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
            + path.read_bytes()
        )
        body_parts.append(f"\r\n--{boundary}--\r\n".encode())
        multipart_body = b"\r\n".join(body_parts)

        upload_req = urllib.request.Request(
            upload_url,
            data=multipart_body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(upload_req, timeout=60) as r:
            pass  # S3 returns 204

        # Create the file in Shopify Files
        create_query = {
            "query": """
            mutation fileCreate($files: [FileCreateInput!]!) {
              fileCreate(files: $files) {
                files { id ... on MediaImage { image { url } } ... on GenericFile { url } }
                userErrors { field message }
              }
            }
            """,
            "variables": {
                "files": [{
                    "originalSource": resource_url,
                    "contentType":    "FILE",
                }]
            }
        }
        req2 = urllib.request.Request(
            gql_url,
            data=json.dumps(create_query).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            create_data = json.loads(r.read())

        files = (
            create_data.get("data", {})
            .get("fileCreate", {})
            .get("files", [])
        )
        file_url = files[0].get("url", resource_url) if files else resource_url
        file_id  = files[0].get("id", "") if files else ""

        _add_log(f"✅ Digital file uploaded: {fname}")
        return {"success": True, "file_url": file_url, "file_id": file_id, "filename": fname}

    except Exception as e:
        _add_log(f"File upload error: {e}", "ERROR")
        return {"success": False, "error": str(e)}


def attach_download_to_product(variant_id: int, file_url: str, filename: str) -> dict:
    """
    Use Shopify's Digital Downloads app approach via metafield to attach
    a download URL to a product variant.
    """
    payload = {
        "metafield": {
            "namespace": "digital_downloads",
            "key":       "download_url",
            "value":     file_url,
            "type":      "url",
        }
    }
    result = _api("POST", f"variants/{variant_id}/metafields.json", payload)
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True, "metafield": result.get("metafield", {})}


# ══════════════════════════════════════════════════════════════════════════════
# ORDERS
# ══════════════════════════════════════════════════════════════════════════════

def list_orders(limit: int = 50, status: str = "any", since_id: int = 0) -> list:
    """List orders. status: 'open'|'closed'|'cancelled'|'any'"""
    params = f"limit={limit}&status={status}"
    if since_id:
        params += f"&since_id={since_id}"
    result = _api("GET", f"orders.json?{params}")
    return result.get("orders", [])


def get_order(order_id: int) -> dict:
    result = _api("GET", f"orders/{order_id}.json")
    return result.get("order", {})


def get_orders_summary(days: int = 30) -> dict:
    """Return revenue summary for the last N days."""
    orders = list_orders(limit=250, status="any")
    total  = sum(float(o.get("total_price", 0)) for o in orders)
    paid   = [o for o in orders if o.get("financial_status") == "paid"]
    return {
        "total_orders":  len(orders),
        "paid_orders":   len(paid),
        "total_revenue": round(total, 2),
        "currency":      orders[0].get("currency", "USD") if orders else "USD",
        "recent":        orders[:10],
    }


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOMERS
# ══════════════════════════════════════════════════════════════════════════════

def list_customers(limit: int = 50) -> list:
    result = _api("GET", f"customers.json?limit={limit}")
    return result.get("customers", [])


def get_customer(customer_id: int) -> dict:
    result = _api("GET", f"customers/{customer_id}.json")
    return result.get("customer", {})


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY
# ══════════════════════════════════════════════════════════════════════════════

def list_locations() -> list:
    result = _api("GET", "locations.json")
    return result.get("locations", [])


def get_inventory_level(inventory_item_id: int) -> dict:
    result = _api("GET", f"inventory_levels.json?inventory_item_ids={inventory_item_id}")
    levels = result.get("inventory_levels", [])
    return levels[0] if levels else {}


# ══════════════════════════════════════════════════════════════════════════════
# PRICE RULES & DISCOUNT CODES
# ══════════════════════════════════════════════════════════════════════════════

def create_discount_code(
    title: str,
    code: str,
    percent_off: float = 0,
    amount_off: float = 0,
    usage_limit: int = 100,
    ends_at: str = "",
) -> dict:
    """
    Create a price rule + discount code.
    Pass either percent_off (e.g. 20 = 20% off) or amount_off (e.g. 5 = $5 off).
    """
    value_type = "percentage" if percent_off else "fixed_amount"
    value      = f"-{percent_off}" if percent_off else f"-{amount_off}"

    payload = {
        "price_rule": {
            "title":              title,
            "target_type":        "line_item",
            "target_selection":   "all",
            "allocation_method":  "across",
            "value_type":         value_type,
            "value":              value,
            "customer_selection": "all",
            "usage_limit":        usage_limit,
            "starts_at":          _now(),
        }
    }
    if ends_at:
        payload["price_rule"]["ends_at"] = ends_at

    rule_result = _api("POST", "price_rules.json", payload)
    if "error" in rule_result:
        return {"success": False, "error": rule_result["error"]}

    rule_id = rule_result.get("price_rule", {}).get("id")
    code_result = _api(
        "POST",
        f"price_rules/{rule_id}/discount_codes.json",
        {"discount_code": {"code": code.upper()}},
    )
    if "error" in code_result:
        return {"success": False, "error": code_result["error"]}

    _add_log(f"✅ Discount code created: {code.upper()} ({value_type}: {value})")
    return {
        "success":      True,
        "rule_id":      rule_id,
        "discount_code": code.upper(),
        "value_type":   value_type,
        "value":        value,
    }


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOKS
# ══════════════════════════════════════════════════════════════════════════════

WEBHOOK_TOPICS = [
    "orders/create",
    "orders/paid",
    "orders/cancelled",
    "products/create",
    "products/update",
    "customers/create",
    "app/uninstalled",
]


def register_webhooks(base_url: str = "") -> list:
    """
    Register all webhook topics to point at our server.
    Call this once after OAuth completes.
    """
    if not base_url:
        base_url = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")

    results = []
    for topic in WEBHOOK_TOPICS:
        payload = {
            "webhook": {
                "topic":   topic,
                "address": f"{base_url}/api/shopify/webhook",
                "format":  "json",
            }
        }
        r = _api("POST", "webhooks.json", payload)
        ok = "webhook" in r
        results.append({"topic": topic, "registered": ok, "error": r.get("error", "")})
        if ok:
            _add_log(f"Webhook registered: {topic}")

    return results


def list_webhooks() -> list:
    result = _api("GET", "webhooks.json")
    return result.get("webhooks", [])


# ══════════════════════════════════════════════════════════════════════════════
# NARAI → SHOPIFY AUTO-PUBLISH
# ══════════════════════════════════════════════════════════════════════════════

def publish_narai_product(product_package: dict) -> dict:
    """
    Publish a NarAI digital product package to Shopify.
    Handles: product creation, cover image upload, digital file attachment,
             and launch discount code creation.

    Args:
        product_package: output from build_complete_product_package() or
                         build_gumroad_product_package()

    Returns:
        {success, product_id, product_url, discount_code, errors[]}
    """
    if not is_connected():
        return {"success": False, "error": "Shopify not connected — run OAuth first"}

    title        = product_package.get("title", "Untitled Product")
    description  = product_package.get("sales_page") or product_package.get("listing_content", "")
    price        = float(product_package.get("price", 19.99))
    niche        = product_package.get("niche", "Digital Products")
    ptype        = product_package.get("product_type", "ebook")
    keywords     = (
        product_package.get("concept", {}).get("keywords")
        or product_package.get("strategy", {}).get("keywords", [])
    )
    pricing      = product_package.get("pricing", {})
    cover_image  = product_package.get("cover_image", {})
    disclaimer   = product_package.get("disclaimer", "")

    errors = []

    # ── 1. Create product ─────────────────────────────────────────────────────
    _add_log(f"Publishing '{title}' to Shopify…")

    # Convert markdown description to basic HTML
    html_desc = description.replace("\n\n", "</p><p>").replace("\n", "<br/>")
    html_desc = f"<p>{html_desc}</p>"
    if disclaimer:
        html_desc += f"<hr/><p><small>{disclaimer}</small></p>"

    product_result = create_product(
        title=title,
        description=html_desc,
        price=price,
        product_type=niche,
        tags=keywords[:10] if keywords else [niche, "digital download", ptype],
        requires_shipping=False,
    )

    if not product_result.get("success"):
        return {"success": False, "error": product_result.get("error"), "errors": [product_result.get("error")]}

    product_id = product_result["product_id"]
    product    = product_result.get("product", {})
    variant_id = product.get("variants", [{}])[0].get("id")

    # ── 2. Upload cover image ─────────────────────────────────────────────────
    cover_local = cover_image.get("local_path", "")
    cover_url   = cover_image.get("url", "")

    if cover_local and Path(cover_local).exists():
        img_result = add_product_image(product_id, image_path=cover_local)
        if not img_result.get("success"):
            errors.append(f"Cover image: {img_result.get('error')}")
    elif cover_url:
        img_result = add_product_image(product_id, image_url=cover_url)
        if not img_result.get("success"):
            errors.append(f"Cover image URL: {img_result.get('error')}")

    # ── 3. Upload digital file (PDF) if available ─────────────────────────────
    delivery  = product_package.get("delivery", {})
    main_files = delivery.get("main_files", [])
    pkg_path   = product_package.get("package_path", "")

    # Try to find an actual PDF to attach
    pdf_uploaded = False
    for file_info in main_files[:1]:   # attach the primary file
        fname    = file_info.get("filename", "")
        pkg_dir  = Path(pkg_path).parent if pkg_path else DATA_DIR / "narai_products"
        pdf_path = pkg_dir / fname
        if pdf_path.exists():
            upload_result = upload_digital_file(str(pdf_path), fname)
            if upload_result.get("success") and variant_id:
                attach_result = attach_download_to_product(
                    variant_id,
                    upload_result["file_url"],
                    fname,
                )
                if attach_result.get("success"):
                    pdf_uploaded = True
                    _add_log(f"✅ Digital file attached: {fname}")
                else:
                    errors.append(f"Attach file: {attach_result.get('error')}")
            elif not upload_result.get("success"):
                errors.append(f"Upload file: {upload_result.get('error')}")

    # ── 4. Create launch discount code ───────────────────────────────────────
    launch_price = pricing.get("launch_price") or pricing.get("entry", {}).get("price")
    discount_code_str = ""
    if launch_price and float(launch_price) < price:
        discount_pct = round((1 - float(launch_price) / price) * 100)
        safe_title   = "".join(c for c in title[:12] if c.isalnum()).upper()
        code         = f"{safe_title}LAUNCH"
        disc_result  = create_discount_code(
            title=f"Launch discount for {title[:40]}",
            code=code,
            percent_off=discount_pct,
            usage_limit=50,
        )
        if disc_result.get("success"):
            discount_code_str = disc_result["discount_code"]
            _add_log(f"✅ Launch code: {discount_code_str} ({discount_pct}% off)")
        else:
            errors.append(f"Discount code: {disc_result.get('error')}")

    shop, *_ = get_credentials()
    _add_log(
        f"✅ Shopify publish complete: '{title}' "
        f"(ID {product_id}, digital={pdf_uploaded}, code={discount_code_str or 'none'})"
    )

    return {
        "success":       True,
        "product_id":    product_id,
        "product_url":   product_result.get("product_url", ""),
        "admin_url":     product_result.get("admin_url", ""),
        "discount_code": discount_code_str,
        "pdf_uploaded":  pdf_uploaded,
        "errors":        errors,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════

def get_status() -> dict:
    """Return full Shopify connection + store status."""
    shop, token, _ = get_credentials()
    tok = _load_token()
    connected = bool(shop and token)

    status = {
        "connected":    connected,
        "shop":         shop,
        "connected_at": tok.get("connected_at", ""),
        "scope":        tok.get("scope", ""),
        "api_version":  API_VERSION,
    }

    if connected:
        try:
            info = _api("GET", "shop.json")
            shop_info = info.get("shop", {})
            summary   = get_orders_summary()
            products  = list_products(limit=10)
            status.update({
                "shop_name":     shop_info.get("name", ""),
                "shop_email":    shop_info.get("email", ""),
                "currency":      shop_info.get("currency", "USD"),
                "plan":          shop_info.get("plan_name", ""),
                "total_orders":  summary.get("total_orders", 0),
                "total_revenue": summary.get("total_revenue", 0),
                "products_count": len(products),
                "recent_products": [
                    {"id": p["id"], "title": p["title"], "status": p.get("status")}
                    for p in products[:5]
                ],
            })
        except Exception as e:
            status["error"] = str(e)

    return status
