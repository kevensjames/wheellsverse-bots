"""base compat: create the Supabase-owned base tables so the chain builds standalone

Path X: identity + chat history live in Supabase-managed tables (public.profiles,
public.conversations, public.messages) created by Supabase auth/migrations in
production. The rest of the Alembic chain (0001+) assumes they already exist:
0003 FKs memories -> profiles, 0005 ALTERs conversations/messages. On a fresh
isolated database (local / staging) those base tables are absent, so
``alembic upgrade head`` used to fail (relation "profiles"/"conversations" does
not exist) and required a create_all/stamp workaround.

This migration is the base of the chain and creates those tables **idempotently**
(CREATE TABLE IF NOT EXISTS + extension IF NOT EXISTS). Prod safety:
  * Production DBs are already stamped past this revision, so it never re-runs there.
  * Even if it did, IF NOT EXISTS makes it a no-op against the real Supabase tables —
    it never drops, alters, or conflicts with existing data.
Columns mirror app/models/{profile,conversation}.py. Later migrations that ADD
columns (0005) all use ADD COLUMN IF NOT EXISTS, so they no-op here.

Revision ID: 0000_base_compat
Revises: (base)
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "0000_base_compat"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # gen_random_uuid() lives in pgcrypto; 0001 also ensures it, but this runs first.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # public.profiles — canonical user table (Supabase-owned in prod). Mirrors
    # app/models/profile.py. Idempotent: never touches an existing prod table.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email text NOT NULL UNIQUE,
            name text,
            avatar_url text,
            tier text NOT NULL DEFAULT 'free',
            messages_used_today integer NOT NULL DEFAULT 0,
            last_reset_date date NOT NULL DEFAULT CURRENT_DATE,
            stripe_customer_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT profiles_tier_check CHECK (tier IN ('free','pro','max','ultra'))
        )
        """
    )

    # public.conversations — Supabase-owned. Mirrors app/models/conversation.py
    # (incl. the 0005 `metadata` column, whose ADD is IF NOT EXISTS → no-op).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            title text,
            model_used text,
            message_count integer NOT NULL DEFAULT 0,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # public.messages — Supabase-owned. Mirrors app/models/conversation.py Message
    # (incl. the 0005 tool-loop columns, whose ADDs are IF NOT EXISTS → no-op).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            role text NOT NULL,
            content text NOT NULL,
            model_used text,
            tokens_used integer,
            tool_calls jsonb,
            tool_call_id varchar(100),
            tool_name varchar(100),
            adapter varchar(50),
            cost_usd numeric(10, 6),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    # Intentionally NON-destructive: these base tables are Supabase-owned in
    # production and may hold real identity + chat history. Dropping them on a
    # downgrade would be catastrophic and is out of this migration's remit.
    # (Documented irreversible per the migration-safety policy §4.)
    pass
