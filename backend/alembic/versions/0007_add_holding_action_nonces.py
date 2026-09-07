"""add holding_action_nonces — one-time consumption of execution confirmations

Revision ID: 0007_add_holding_action_nonces
Revises: 0006_add_kai_api_keys
Create Date: 2026-09-07

An owner's execution confirmation is a short-lived signed token. Signature validity alone makes it
REPLAYABLE inside its window: the same token verifies every time it is presented. This table is what
makes a confirmation single-use.

The primary key on ``jti`` is the whole mechanism. Consumption is
``INSERT ... ON CONFLICT (jti) DO NOTHING RETURNING jti`` — the DATABASE picks the winner, so:
  • concurrent gunicorn workers race on the key and exactly one INSERT returns a row;
  • the decision survives a restart, because it is a committed row and not process memory;
  • an unreachable table makes the caller fail CLOSED (the action is refused, never allowed).

WHAT IS NOT STORED. No token, no signature, no confirmation body, no credential, no secret, and no
action payload. Only the nonce and the binding facts needed to audit and expire a consumption. The
jti is random and carries no authority on its own: possessing a row grants nothing, and the row exists
precisely to prove the token behind it can never be used again.

ADDITIVE AND ROLLBACK-SAFE. Nothing else references this table. Rolling application code back to a
version that does not know about it leaves it inert — an unread table, not a broken constraint. The
downgrade therefore does NOT drop it: these rows are audit evidence of executions that really
happened, and destroying them to undo a code deploy would be exactly the history-erasure this system
exists to prevent. Dropping it is a deliberate, separate operator action.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0007_add_holding_action_nonces"
down_revision: Union[str, None] = "0006_add_kai_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS throughout: this table may already exist on an environment that ran the earlier
    # build, which created it implicitly at call time. Re-running the migration must be a no-op, and
    # adopting an already-present table must not fail.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS holding_action_nonces (
            jti           TEXT PRIMARY KEY,
            proposal_id   TEXT        NOT NULL,
            principal_id  TEXT        NOT NULL,
            environment   TEXT        NOT NULL,
            action_digest TEXT,
            expires_at    TIMESTAMPTZ NOT NULL,
            consumed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Adopt a table created by the earlier implicit DDL, which lacked action_digest.
    op.execute("ALTER TABLE holding_action_nonces ADD COLUMN IF NOT EXISTS action_digest TEXT")
    # Retention sweeps delete by expiry; auditing reads by proposal. Both want an index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS holding_action_nonces_expires_at "
        "ON holding_action_nonces (expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS holding_action_nonces_proposal "
        "ON holding_action_nonces (proposal_id, consumed_at DESC)"
    )


def downgrade() -> None:
    # Deliberately NOT a DROP TABLE.
    #
    # These rows record that specific execution confirmations were consumed — audit evidence of
    # actions that really occurred. A downgrade exists to roll application CODE back, and code
    # rollback must never destroy evidence. The table is additive and unreferenced, so leaving it in
    # place is harmless to any older code version.
    #
    # Only the indexes are removed, since they are a pure performance artifact of this revision.
    op.execute("DROP INDEX IF EXISTS holding_action_nonces_proposal")
    op.execute("DROP INDEX IF EXISTS holding_action_nonces_expires_at")
