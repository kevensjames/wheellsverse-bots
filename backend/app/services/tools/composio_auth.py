"""Composio user-id resolution.

Maps NAI's per-request user_id (a UUID from ToolContext) to whatever string
Composio has the user's SaaS connections registered under.

Phase A (single-operator NAI): env override wins. Set ``COMPOSIO_USER_ID`` in
the environment to the string Composio uses for your connections (visible in
``client.connected_accounts.list()[i].user_id``).

Phase B (multi-tenant): replace this function with a DB lookup that returns
``profiles.composio_user_id`` for the NAI user, falling back to the env
override if the column is null. The single call-site in both Composio tools
makes that swap a 5-line change.
"""
from __future__ import annotations

import os
import uuid


def resolve_composio_user_id(ctx_user_id: uuid.UUID | str) -> str:
    """Return the user_id string to pass to Composio for this NAI user.

    Order of precedence:
        1. ``COMPOSIO_USER_ID`` env var if set (Phase A — single-operator)
        2. ``str(ctx_user_id)`` (NAI's UUID, ideal once connections are
            registered under it)

    Notably this returns a STRING — Composio's user_id is freeform text,
    not strictly a UUID. The override commonly looks like ``pg-test-…`` when
    set via Composio's dashboard playground, or ``user@example.com``, or any
    operator-chosen identifier.
    """
    override = os.environ.get("COMPOSIO_USER_ID")
    if override:
        return override
    return str(ctx_user_id)
