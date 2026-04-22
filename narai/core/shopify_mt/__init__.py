"""
narai.core.shopify_mt
─────────────────────────────────────────────────────────────────────────────
Multi-tenant Shopify integration for NarAI.

Submodules:
  crypto      — Fernet encrypt/decrypt for merchant access tokens
  db          — Supabase CRUD for merchants / merchant_products / events / billing
  oauth       — Install + callback flow (Shopify OAuth)
  webhooks    — HMAC-verified webhook receivers (app/uninstalled, GDPR, etc.)
  products    — Multi-tenant product pipeline (DALL-E → gate → Shopify → Printify)
  billing     — Stripe Checkout + plan gating for merchants
─────────────────────────────────────────────────────────────────────────────
"""
