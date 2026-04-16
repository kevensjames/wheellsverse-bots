#!/usr/bin/env python3
"""
Run this once to save your Twitter/X session:
    python twitter_login.py

A browser window will open. Log in normally, then press ENTER here.
The session is saved to data/cookies/twitter_session.json and reused
automatically by all bots.
"""
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).parent
COOKIES_FILE = ROOT / "data" / "cookies" / "twitter_session.json"
COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)


async def main():
    from playwright.async_api import async_playwright

    print("\n🌐 Opening browser for manual Twitter/X login...")
    print("   Log in normally, then come back here and press ENTER.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        await page.goto("https://x.com/login")

        # Wait for user to log in
        print("   ↳ Log in to X in the browser window...")
        input("   ↳ Once logged in, press ENTER here to save session: ")

        cookies = await ctx.cookies()
        await browser.close()

    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    print(f"\n✅ Session saved → {COOKIES_FILE}")
    print("   All bots will now post to Twitter automatically.\n")


if __name__ == "__main__":
    asyncio.run(main())
