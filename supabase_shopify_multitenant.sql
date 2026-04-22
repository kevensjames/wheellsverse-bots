-- ═══════════════════════════════════════════════════════════════════════════
-- NarAI × Shopify Multi-Tenant Schema (Phase 1)
-- ═══════════════════════════════════════════════════════════════════════════
-- Run in Supabase SQL Editor AFTER supabase_schema.sql.
-- Adds 4 tables for managing connected merchant Shopify stores.
-- All tokens encrypted at rest via Fernet (encryption happens in app code).
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── 1. merchants ──────────────────────────────────────────────────────────
-- Every connected Shopify store gets one row here.
CREATE TABLE IF NOT EXISTS public.merchants (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_domain             TEXT NOT NULL UNIQUE,                       -- e.g. 'acme.myshopify.com'
    access_token_encrypted  TEXT NOT NULL,                              -- Fernet ciphertext, never plaintext
    scopes                  TEXT NOT NULL DEFAULT '',                   -- 'read_products,write_products,...'
    installed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uninstalled_at          TIMESTAMPTZ,                                -- NULL = active, non-NULL = soft-deleted
    owner_email             TEXT,
    shop_name               TEXT,
    shop_country            TEXT,
    shop_currency           TEXT DEFAULT 'USD',
    plan_tier               TEXT NOT NULL DEFAULT 'free'
                            CHECK (plan_tier IN ('free','starter','pro','elite')),
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    grace_period_until      TIMESTAMPTZ,                                -- set when payment fails
    last_synced_at          TIMESTAMPTZ,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merchants_shop_domain ON public.merchants(shop_domain);
CREATE INDEX IF NOT EXISTS idx_merchants_plan_tier   ON public.merchants(plan_tier)
    WHERE uninstalled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_merchants_active      ON public.merchants(installed_at DESC)
    WHERE uninstalled_at IS NULL;


-- ─── 2. merchant_products ──────────────────────────────────────────────────
-- Every product NarAI creates or syncs on a merchant's store.
CREATE TABLE IF NOT EXISTS public.merchant_products (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id             UUID NOT NULL REFERENCES public.merchants(id) ON DELETE CASCADE,
    shopify_product_id      BIGINT NOT NULL,
    shopify_handle          TEXT,
    title                   TEXT NOT NULL,
    source                  TEXT NOT NULL
                            CHECK (source IN ('dalle','printify','manual','migrated')),
    images_count            INT NOT NULL DEFAULT 0,
    quality_gate_passed     BOOLEAN NOT NULL DEFAULT FALSE,
    published               BOOLEAN NOT NULL DEFAULT FALSE,
    printify_product_id     TEXT,
    price_cents             INT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (merchant_id, shopify_product_id)
);

CREATE INDEX IF NOT EXISTS idx_merchant_products_merchant   ON public.merchant_products(merchant_id);
CREATE INDEX IF NOT EXISTS idx_merchant_products_published  ON public.merchant_products(merchant_id, published);
CREATE INDEX IF NOT EXISTS idx_merchant_products_created    ON public.merchant_products(created_at DESC);


-- ─── 3. merchant_events ────────────────────────────────────────────────────
-- Append-only audit log of every action NarAI takes on a merchant store.
CREATE TABLE IF NOT EXISTS public.merchant_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES public.merchants(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,    -- 'install','uninstall','product.create','product.update',
                                      -- 'webhook.received','webhook.rejected','billing.charge',
                                      -- 'billing.failed','plan.upgraded','plan.downgraded',
                                      -- 'gdpr.customers_data_request','gdpr.customers_redact','gdpr.shop_redact'
    severity        TEXT NOT NULL DEFAULT 'info'
                    CHECK (severity IN ('info','warn','error')),
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merchant_events_merchant   ON public.merchant_events(merchant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_merchant_events_type       ON public.merchant_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_merchant_events_severity   ON public.merchant_events(severity, created_at DESC)
    WHERE severity != 'info';


-- ─── 4. merchant_billing ───────────────────────────────────────────────────
-- Every Stripe event (charge/refund/failure) logged per merchant.
CREATE TABLE IF NOT EXISTS public.merchant_billing (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id         UUID NOT NULL REFERENCES public.merchants(id) ON DELETE CASCADE,
    stripe_event_id     TEXT NOT NULL UNIQUE,                    -- dedupe on Stripe event IDs
    stripe_event_type   TEXT NOT NULL,                           -- 'checkout.session.completed', etc.
    amount_cents        INT,
    currency            TEXT DEFAULT 'usd',
    status              TEXT NOT NULL,                           -- 'succeeded','failed','pending','refunded'
    stripe_invoice_id   TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merchant_billing_merchant  ON public.merchant_billing(merchant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_merchant_billing_status    ON public.merchant_billing(status)
    WHERE status IN ('failed','pending');


-- ─── 5. Auto-update updated_at trigger ─────────────────────────────────────
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_merchants_updated_at          ON public.merchants;
DROP TRIGGER IF EXISTS trg_merchant_products_updated_at  ON public.merchant_products;
CREATE TRIGGER trg_merchants_updated_at          BEFORE UPDATE ON public.merchants
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_merchant_products_updated_at  BEFORE UPDATE ON public.merchant_products
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ─── 6. Row Level Security ─────────────────────────────────────────────────
-- These tables are ONLY accessed from the backend with the service_role key.
-- RLS is enabled and policies DENY all by default — no client-side access.
ALTER TABLE public.merchants          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.merchant_products  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.merchant_events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.merchant_billing   ENABLE ROW LEVEL SECURITY;

-- (Service role bypasses RLS automatically — no policies needed for backend.)
-- If you ever want admins to read via the client, add a policy keyed on auth.uid().


-- ─── 7. Verification ───────────────────────────────────────────────────────
-- Sanity check the install.
DO $$
BEGIN
    RAISE NOTICE 'NarAI × Shopify multi-tenant schema installed successfully.';
    RAISE NOTICE 'Tables: merchants, merchant_products, merchant_events, merchant_billing';
END $$;
