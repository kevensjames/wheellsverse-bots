#!/usr/bin/env python3
"""
setup_meta_tokens.py
─────────────────────────────────────────────────────────────────────────────
Interactive setup for Facebook Page Token + Instagram Account ID.

Run this once:
  python setup_meta_tokens.py

It will:
  1. Open the Meta Graph API Explorer in your browser
  2. Walk you through copying your Page Access Token
  3. Auto-discover your Page ID and Instagram Account ID
  4. Test that posting works
  5. Save everything to .env
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import re
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"
load_dotenv(ENV_FILE)


def _print(msg, color="reset"):
    colors = {"green": "\033[92m", "yellow": "\033[93m",
              "red": "\033[91m", "cyan": "\033[96m", "reset": "\033[0m"}
    print(f"{colors.get(color, '')}{msg}{colors['reset']}")


def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val or default


# ── Step 1: Get a User Access Token from Graph API Explorer ───────────────────

def open_graph_explorer():
    _print("\n" + "=" * 60, "cyan")
    _print("  STEP 1 — Get your Facebook Page Access Token", "cyan")
    _print("=" * 60, "cyan")
    print("""
Follow these steps:

  1. Opening Meta Graph API Explorer in your browser...
  2. In the top-right, click "Generate Access Token"
  3. Select your App (or create one at developers.facebook.com)
  4. Grant these permissions:
       ✅ pages_manage_posts
       ✅ pages_read_engagement
       ✅ instagram_basic
       ✅ instagram_content_publish
  5. Click "Generate Access Token" and COPY the token
  6. Paste it below
""")
    webbrowser.open("https://developers.facebook.com/tools/explorer/")


def get_long_lived_token(short_token: str) -> str:
    """Exchange short-lived token for a 60-day long-lived token."""
    app_id = os.getenv("META_APP_ID", "")
    app_secret = os.getenv("META_APP_SECRET", "")

    if not app_id or not app_secret:
        _print("\n⚠️  META_APP_ID / META_APP_SECRET not set — using token as-is (may expire in 1 hour)", "yellow")
        _print("   To get a 60-day token, add META_APP_ID and META_APP_SECRET to .env", "yellow")
        return short_token

    resp = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=15,
    )
    data = resp.json()
    if "access_token" in data:
        expires = data.get("expires_in", 0)
        _print(f"  ✅ Long-lived token obtained (expires in {expires // 86400} days)", "green")
        return data["access_token"]
    _print(f"  ⚠️  Could not exchange token: {data} — using original", "yellow")
    return short_token


# ── Step 2: Discover Page ID ──────────────────────────────────────────────────

def discover_pages(token: str) -> list:
    """List all Facebook Pages the token has access to."""
    resp = requests.get(
        "https://graph.facebook.com/v19.0/me/accounts",
        params={"access_token": token, "fields": "id,name,access_token"},
        timeout=15,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Token error: {data['error']['message']}")
    return data.get("data", [])


def choose_page(pages: list) -> dict:
    _print("\n" + "=" * 60, "cyan")
    _print("  STEP 2 — Choose your Facebook Page", "cyan")
    _print("=" * 60, "cyan")
    print()
    for i, page in enumerate(pages, 1):
        print(f"  {i}. {page['name']}  (ID: {page['id']})")
    print()
    while True:
        choice = input(f"  Enter number [1-{len(pages)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(pages):
            return pages[int(choice) - 1]
        _print("  Invalid choice — try again", "red")


# ── Step 3: Discover Instagram Account ID ─────────────────────────────────────

def discover_instagram(page_id: str, page_token: str) -> str:
    """Get the Instagram Business Account ID linked to the FB Page."""
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/{page_id}",
        params={"fields": "instagram_business_account", "access_token": page_token},
        timeout=15,
    )
    data = resp.json()
    ig = data.get("instagram_business_account", {})
    return ig.get("id", "")


# ── Step 4: Test posting ──────────────────────────────────────────────────────

def test_facebook_post(page_id: str, page_token: str) -> bool:
    _print("\n  Testing Facebook post...", "yellow")
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{page_id}/feed",
        json={
            "message": "🤖 WheellsVerse autopilot is now connected! Daily AI + passive income content coming your way. #AI #WheellsVerse",
            "access_token": page_token,
        },
        timeout=15,
    )
    data = resp.json()
    if "id" in data:
        _print(f"  ✅ Facebook test post live! ID: {data['id']}", "green")
        return True
    _print(f"  ❌ Facebook post failed: {data.get('error', {}).get('message', str(data))}", "red")
    return False


def test_instagram_post(ig_account_id: str, page_token: str, openai_key: str) -> bool:
    _print("\n  Testing Instagram post...", "yellow")
    if not openai_key:
        _print("  ⚠️  OPENAI_API_KEY not set — skipping Instagram test (image required)", "yellow")
        return True

    # Generate a test image
    try:
        from openai import OpenAI
        img = OpenAI(api_key=openai_key).images.generate(
            model="dall-e-3",
            prompt="WheellsVerse AI brand — dark futuristic tech, cyan glowing text: 'Autopilot Connected', minimal and powerful",
            size="1024x1024", quality="standard", n=1,
        )
        image_url = img.data[0].url
    except Exception as e:
        _print(f"  ⚠️  Image generation failed: {e} — skipping IG test", "yellow")
        return True

    # Create container
    container = requests.post(
        f"https://graph.facebook.com/v19.0/{ig_account_id}/media",
        data={"image_url": image_url,
              "caption": "🤖 WheellsVerse autopilot connected! Daily AI + passive income drops. Follow for daily signals. #AI #PassiveIncome #WheellsVerse",
              "access_token": page_token},
        timeout=30,
    ).json()
    if "id" not in container:
        _print(f"  ❌ IG container error: {container.get('error', {}).get('message', str(container))}", "red")
        return False

    import time
    time.sleep(3)
    publish = requests.post(
        f"https://graph.facebook.com/v19.0/{ig_account_id}/media_publish",
        data={"creation_id": container["id"], "access_token": page_token},
        timeout=30,
    ).json()
    if "id" in publish:
        _print(f"  ✅ Instagram test post live! ID: {publish['id']}", "green")
        return True
    _print(f"  ❌ IG publish error: {publish.get('error', {}).get('message', str(publish))}", "red")
    return False


# ── Step 5: Save to .env ──────────────────────────────────────────────────────

def save_to_env(page_token: str, page_id: str, ig_account_id: str):
    _print("\n  Saving to .env...", "yellow")

    def _set(key, val):
        # Try set_key first; if the key exists as a comment stub, replace it
        content = ENV_FILE.read_text()
        pattern = rf'^({re.escape(key)}=).*$'
        if re.search(pattern, content, re.MULTILINE):
            new_content = re.sub(pattern, rf'\g<1>{val}', content, flags=re.MULTILINE)
            ENV_FILE.write_text(new_content)
        else:
            set_key(str(ENV_FILE), key, val)

    _set("FACEBOOK_PAGE_TOKEN", page_token)
    _set("FACEBOOK_PAGE_ID", page_id)
    _set("INSTAGRAM_PAGE_TOKEN", page_token)  # same token
    _set("INSTAGRAM_ACCOUNT_ID", ig_account_id)

    _print("  ✅ Saved:", "green")
    _print(f"     FACEBOOK_PAGE_TOKEN = {page_token[:20]}...", "green")
    _print(f"     FACEBOOK_PAGE_ID    = {page_id}", "green")
    _print("     INSTAGRAM_PAGE_TOKEN = (same token)", "green")
    _print(f"     INSTAGRAM_ACCOUNT_ID = {ig_account_id or '(not found — set manually)'}", "green")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _print("\n🚀 WheellsVerse — Meta (Facebook + Instagram) Setup", "cyan")
    _print("   This will connect your Facebook Page and Instagram account\n", "cyan")

    # Step 1 — Get token
    open_graph_explorer()
    token = ""
    while not token:
        token = input("  Paste your Access Token here: ").strip()
        if not token:
            _print("  Token cannot be empty — try again", "red")

    # Exchange for long-lived token
    token = get_long_lived_token(token)

    # Step 2 — Discover pages
    _print("\n  Fetching your Facebook Pages...", "yellow")
    try:
        pages = discover_pages(token)
    except RuntimeError as e:
        _print(f"\n❌ {e}", "red")
        _print("   Check your token has the right permissions and try again.", "red")
        sys.exit(1)

    if not pages:
        _print("\n❌ No Facebook Pages found for this token.", "red")
        _print("   Make sure you granted 'pages_manage_posts' permission.", "red")
        sys.exit(1)

    # Step 3 — Choose page
    if len(pages) == 1:
        page = pages[0]
        _print(f"\n  Using page: {page['name']} (ID: {page['id']})", "green")
    else:
        page = choose_page(pages)

    page_token = page.get("access_token") or token  # Page token is more reliable
    page_id = page["id"]
    _print(f"\n  ✅ Page selected: {page['name']} — ID: {page_id}", "green")

    # Step 4 — Instagram Account ID
    _print("\n" + "=" * 60, "cyan")
    _print("  STEP 3 — Linking Instagram Business Account", "cyan")
    _print("=" * 60, "cyan")
    _print("\n  Looking for Instagram account linked to your Facebook Page...", "yellow")
    ig_account_id = discover_instagram(page_id, page_token)
    if ig_account_id:
        _print(f"  ✅ Instagram Account ID found: {ig_account_id}", "green")
    else:
        _print("\n  ⚠️  No Instagram Business account found linked to this Page.", "yellow")
        _print("  To link it:", "yellow")
        _print("    1. Go to your Facebook Page → Settings → Instagram", "yellow")
        _print("    2. Connect your Instagram Business account", "yellow")
        _print("    3. Re-run this script\n", "yellow")
        ig_account_id = _ask("  Or enter your Instagram Account ID manually (leave blank to skip)", "")

    # Step 5 — Test
    _print("\n" + "=" * 60, "cyan")
    _print("  STEP 4 — Testing connections", "cyan")
    _print("=" * 60, "cyan")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    fb_ok = test_facebook_post(page_id, page_token)
    ig_ok = test_instagram_post(ig_account_id, page_token, openai_key) if ig_account_id else False

    # Step 6 — Save
    save_to_env(page_token, page_id, ig_account_id)

    # Summary
    _print("\n" + "=" * 60, "cyan")
    _print("  SETUP COMPLETE", "cyan")
    _print("=" * 60, "cyan")
    print()
    _print(f"  Facebook:  {'✅ Connected & tested' if fb_ok else '⚠️  Saved but test failed — check permissions'}", "green" if fb_ok else "yellow")
    _print(f"  Instagram: {'✅ Connected & tested' if ig_ok else '⚠️  ' + ('Saved — run test manually' if ig_account_id else 'Not linked — connect in FB Page Settings')}", "green" if ig_ok else "yellow")
    print()
    _print("  Now publish your 15 posts:", "cyan")
    _print("  python bots/campaigns/viral_post_campaign/publish_campaign.py", "cyan")
    print()
    _print("  Daily NarAI campaign will auto-run at 08:00 every morning.", "cyan")
    print()


if __name__ == "__main__":
    main()
