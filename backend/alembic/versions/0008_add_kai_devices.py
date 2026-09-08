"""add kai_devices, kai_device_pairings, kai_device_nonces — machine principals

Revision ID: 0008_add_kai_devices
Revises: 0007_add_holding_action_nonces
Create Date: 2026-09-08

WHY A NEW PRINCIPAL TYPE. The only existing external-worker credential pattern mints a full owner
session carrying every scope. Giving that to a machine that drives a real desktop would mean a stolen
device credential can do anything the human can, including move money. A device therefore gets its own
identity: it can never be role "owner", it is created with NO scopes, and desktop / browser /
workspace-write / runtime-control each require a separate operator activation afterwards.

WHAT IS STORED. A PUBLIC key, a status, granted scopes, and timestamps. No private key ever reaches
the server — the device proves possession by signing a server-issued challenge, so a full database
read still cannot impersonate a device.

PAIRING CODES ARE STORED HASHED. Only the SHA-256 of a code is written, so reading this table cannot
replay an enrollment. Codes are single-use (``consumed_at``) and short-lived (``expires_at``); the
window in which a code is useful is the window in which a shoulder-surfed or forwarded code enrolls
someone else's machine.

kai_device_nonces mirrors the holding_action_nonces mechanism: the PRIMARY KEY on (device_id, nonce)
is what makes a device authentication single-use. Consumption is
``INSERT ... ON CONFLICT DO NOTHING RETURNING`` so the DATABASE picks the winner across concurrent
workers, the decision survives a restart, and an unreachable table makes the caller fail CLOSED.

ADDITIVE AND ROLLBACK-SAFE. Nothing existing references these tables, so older application code sees
inert, unread tables rather than a broken schema. The downgrade drops only the indexes: device
records are the evidence of which machines were trusted, when, and by whom, and a CODE rollback must
never destroy that. Dropping them is a deliberate, separate operator action.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0008_add_kai_devices"
down_revision: Union[str, None] = "0007_add_holding_action_nonces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kai_devices (
            device_id        TEXT PRIMARY KEY,
            name             TEXT        NOT NULL,
            public_key       BYTEA       NOT NULL,
            status           TEXT        NOT NULL,
            granted_scopes   JSONB       NOT NULL DEFAULT '[]'::jsonb,
            os               TEXT        NOT NULL DEFAULT '',
            arch             TEXT        NOT NULL DEFAULT '',
            enrolled_by      TEXT        NOT NULL DEFAULT '',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            confirmed_at     TIMESTAMPTZ,
            last_seen_at     TIMESTAMPTZ,
            key_rotated_at   TIMESTAMPTZ,
            revoked_at       TIMESTAMPTZ,
            revocation_reason TEXT       NOT NULL DEFAULT ''
        )
        """
    )
    # The panel lists devices by state and staleness; both want an index.
    op.execute("CREATE INDEX IF NOT EXISTS kai_devices_status ON kai_devices (status, last_seen_at DESC)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kai_device_pairings (
            code_hash    TEXT PRIMARY KEY,
            device_name  TEXT        NOT NULL,
            created_by   TEXT        NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at   TIMESTAMPTZ NOT NULL,
            consumed_at  TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS kai_device_pairings_expires ON kai_device_pairings (expires_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kai_device_nonces (
            device_id  TEXT        NOT NULL,
            nonce      TEXT        NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            burned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (device_id, nonce)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS kai_device_nonces_expires ON kai_device_nonces (expires_at)")


def downgrade() -> None:
    # Deliberately NOT a DROP TABLE — see the module docstring. Device records are the audit trail of
    # which machines were trusted and when; a code rollback must not erase it.
    op.execute("DROP INDEX IF EXISTS kai_device_nonces_expires")
    op.execute("DROP INDEX IF EXISTS kai_device_pairings_expires")
    op.execute("DROP INDEX IF EXISTS kai_devices_status")
