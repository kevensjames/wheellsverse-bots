-- ═══════════════════════════════════════════════════════════════════════════
-- SiteBoost CAN-SPAM opt-out list (durable copy of suppressions.json)
-- ═══════════════════════════════════════════════════════════════════════════
-- Run in the Supabase SQL Editor, or:
--   python3 scripts/run_supabase_migration.py narai/migrations/0001_siteboost_suppressions.sql
-- Idempotent: safe to re-run. Plain SQL, not an Alembic revision: Alembic in
-- this folder targets NARAI_DATABASE_URL, not Supabase.
-- Read/written only by core/cold_outreach.py with SUPABASE_SERVICE_KEY
-- (service_role bypasses RLS). RLS is on with NO policies, so the anon and
-- authenticated keys can neither read nor change opt-outs.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.siteboost_suppressions (
    email            TEXT PRIMARY KEY
                     CHECK (email <> '' AND email = lower(btrim(email))),  -- stored lowercased + trimmed
    unsubscribed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    via              TEXT                                                  -- 'click' | 'manual' | 'reply-stop' | ...
);

ALTER TABLE public.siteboost_suppressions ENABLE ROW LEVEL SECURITY;

-- Probe row: before every send, cold_outreach.py must read this back. A key
-- without service_role gets an EMPTY result under RLS (not an error), so a
-- missing probe means "wrong key" and sends are refused. Hidden from the
-- admin list; .invalid can never receive mail. Don't delete it.
INSERT INTO public.siteboost_suppressions (email, via)
VALUES ('__probe__@siteboost.invalid', 'probe')
ON CONFLICT (email) DO NOTHING;
