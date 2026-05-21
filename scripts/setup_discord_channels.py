#!/usr/bin/env python3
"""Idempotent Discord server setup for WheellsVerse / NarAI.

Creates (or repairs) the channel structure mapped to the 6 use cases:
NarAI surface, community, content engine, monetization, ops, growth.

**Permission helpers always include the NarAI bot role with explicit
allow** on locked channels — without this, the bot is locked out of
channels it created (Discord doesn't auto-grant the bot, and Admin is
not implicitly part of the OAuth perms we requested).

Re-running this script is safe:
  • Categories / channels with matching names are reused
  • Channels' permission_overwrites are PATCHed to the canonical set

Requires the bot to have MANAGE_CHANNELS (and MANAGE_ROLES if creating
new roles). If the OAuth grant only included the basic perm set, grant
Administrator temporarily before running.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv("/Users/jhonwheeler/wheellsverse_bots/.env", override=True)

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD = os.environ["DISCORD_GUILD_ID"]
EVERYONE_ID = GUILD                                # Discord convention
INSIDER_ID = os.environ.get("DISCORD_PAID_ROLE_ID", "")
NARAI_BOT_ROLE_ID = "1499324071320748106"          # bot's auto-managed role

VIEW = 0x400
SEND = 0x800
ROLE = 0
API = "https://discord.com/api/v10"

HEADERS = {
    "Authorization": f"Bot {TOKEN}",
    "User-Agent": "WheellsVerse (https://app.wheellsverse.com, 1.0)",
    "Content-Type": "application/json",
}


def _req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"  ! {method} {path} HTTP {e.code}: {e.read().decode()[:240]}", file=sys.stderr)
        raise


def _bot_allow_overwrite() -> dict:
    return {"id": NARAI_BOT_ROLE_ID, "type": ROLE, "allow": str(VIEW | SEND)}


def lock_to_role(role_id: str) -> list[dict]:
    """Hide channel from @everyone, allow ONLY the named role + the bot."""
    return [
        {"id": EVERYONE_ID, "type": ROLE, "deny":  str(VIEW)},
        {"id": role_id,     "type": ROLE, "allow": str(VIEW | SEND)},
        _bot_allow_overwrite(),
    ]


def read_only_for_everyone() -> list[dict]:
    """Anyone can read; only the bot can post."""
    return [
        {"id": EVERYONE_ID, "type": ROLE, "allow": str(VIEW), "deny": str(SEND)},
        _bot_allow_overwrite(),
    ]


def hidden_from_everyone() -> list[dict]:
    """Owner-only channels. The bot still needs explicit allow because
    Administrator was removed from its role after initial grant."""
    return [
        {"id": EVERYONE_ID, "type": ROLE, "deny": str(VIEW)},
        _bot_allow_overwrite(),
    ]


def upsert_category(name: str, by_name: dict) -> str:
    if name in by_name:
        print(f"  category #{name}: reuse {by_name[name]['id']}")
        return by_name[name]["id"]
    res = _req("POST", f"/guilds/{GUILD}/channels", {"name": name, "type": 4})
    by_name[name] = res
    print(f"  category #{name}: created {res['id']}")
    return res["id"]


def upsert_text(name: str, parent_id: str, by_name: dict, *,
                topic: str = "", overwrites: list[dict] | None = None) -> str:
    overwrites = overwrites or []
    if name in by_name:
        ch_id = by_name[name]["id"]
        # Repair: PATCH overwrites to the canonical set (idempotent)
        try:
            _req("PATCH", f"/channels/{ch_id}",
                 {"permission_overwrites": overwrites, "topic": topic})
            print(f"  text #{name}: repaired {ch_id}")
        except urllib.error.HTTPError:
            print(f"  text #{name}: PATCH failed (perms?); existing channel left alone")
        return ch_id
    body = {
        "name": name, "type": 0, "parent_id": parent_id, "topic": topic,
        "permission_overwrites": overwrites,
    }
    res = _req("POST", f"/guilds/{GUILD}/channels", body)
    by_name[name] = res
    print(f"  text #{name}: created {res['id']}")
    return res["id"]


def main() -> int:
    existing = _req("GET", f"/guilds/{GUILD}/channels")
    by_name = {c["name"]: c for c in existing}

    print("📡 NarAI category")
    narai_cat = upsert_category("📡 NarAI", by_name)
    ask_id = upsert_text(
        "ask-narai", narai_cat, by_name,
        topic="Talk to NarAI here. Mention @NarAI or use /ask. PDFs welcome.",
    )
    community_id = upsert_text(
        "community", narai_cat, by_name,
        topic="Open chat — feedback, bugs, intros.",
    )
    signals_id = upsert_text(
        "daily-signals", narai_cat, by_name,
        topic="Auto-posted briefing 7:05am ET, signals 12:05pm, weekly Sun 6:05pm.",
        overwrites=read_only_for_everyone(),
    )

    print("\n💎 Insider category (role-gated)")
    insider_cat = upsert_category("💎 Insider (paid)", by_name)
    if INSIDER_ID:
        insider_overrides = lock_to_role(INSIDER_ID)
    else:
        print("  WARN: DISCORD_PAID_ROLE_ID unset — falling back to hidden_from_everyone")
        insider_overrides = hidden_from_everyone()
    vault_id = upsert_text(
        "insider-vault", insider_cat, by_name,
        topic="Subscribers only. Premium signals, exclusive J.K. Blaze drops.",
        overwrites=insider_overrides,
    )

    print("\n⚙️ Ops category (owner only)")
    ops_cat = upsert_category("⚙️ Ops", by_name)
    status_id = upsert_text(
        "bot-status", ops_cat, by_name,
        topic="Hourly fleet status. Owner-only.",
        overwrites=hidden_from_everyone(),
    )

    print("\n🚀 Growth category")
    growth_cat = upsert_category("🚀 Growth", by_name)
    invite_id = upsert_text(
        "invite-narai", growth_cat, by_name,
        topic="Add NarAI to your own server.",
        overwrites=read_only_for_everyone(),
    )

    print("\nenv vars:")
    print(f"DISCORD_GUILD_ID={GUILD}")
    print(f"DISCORD_GENERAL_CHANNEL_ID={by_name.get('general',{}).get('id','')}")
    print(f"DISCORD_ASK_NARAI_CHANNEL_ID={ask_id}")
    print(f"DISCORD_COMMUNITY_CHANNEL_ID={community_id}")
    print(f"DISCORD_CONTENT_CHANNEL_ID={signals_id}")
    print(f"DISCORD_INSIDER_VAULT_CHANNEL_ID={vault_id}")
    print(f"DISCORD_STATUS_CHANNEL_ID={status_id}")
    print(f"DISCORD_INVITE_CHANNEL_ID={invite_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
