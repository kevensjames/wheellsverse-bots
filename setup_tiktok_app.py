#!/usr/bin/env python3
"""
Fill TikTok Developer Portal app details.
Run: source venv/bin/activate && python setup_tiktok_app.py
"""
import asyncio
from pathlib import Path

ROOT = Path(__file__).parent

WEBSITE_URL = "https://wheellsverse-bots.pages.dev"
TERMS_URL = f"{WEBSITE_URL}/terms.html"
PRIVACY_URL = f"{WEBSITE_URL}/privacy.html"
REDIRECT = "https://grateful-flexibility-production.up.railway.app/api/tiktok/callback"
REVIEW_TEXT = (
    "WheellsVerse automates social media content using AI. "
    "Login Kit is used to authenticate TikTok users and retrieve basic profile info. "
    "Content Posting API with Direct Post publishes AI-generated videos and affiliate "
    "marketing content directly to the authorized user's TikTok profile. "
    "video.upload and video.publish scopes are required for this posting flow. "
    "user.info.basic is needed to display the connected account in our dashboard."
)


async def fill_input_near_label(page, label_text: str, value: str):
    """Find input/textarea that follows a label containing label_text and fill it."""
    try:
        # Try by placeholder
        field = page.get_by_placeholder(label_text, exact=False)
        if await field.count() > 0:
            await field.first.clear()
            await field.first.type(value, delay=30)
            print(f"  ✅ {label_text[:40]}")
            return True
    except Exception:
        pass
    return False


async def main():
    from playwright.async_api import async_playwright

    print("\n🤖 Opening TikTok Developer Portal...")
    print("   Log in if prompted, navigate to your app page, then press ENTER.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60)
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        await page.goto("https://developers.tiktok.com/apps/", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        input("   Navigate to your app's detail page, then press ENTER here: ")
        await page.wait_for_timeout(1000)

        print("\n🖊  Filling fields...\n")

        # ── Category ──────────────────────────────────────────────────────
        try:
            cat = page.locator("select, [class*='select'], [role='combobox']").first
            if await cat.count() > 0:
                await cat.click()
                await page.wait_for_timeout(500)
                opt = page.get_by_role("option").filter(has_text="Entertainment")
                if await opt.count() == 0:
                    opt = page.get_by_role("option").first
                if await opt.count() > 0:
                    await opt.click()
                    print("  ✅ Category selected")
        except Exception as e:
            print(f"  ⚠  Category: {e}")

        # ── Terms of Service URL ───────────────────────────────────────────
        try:
            inputs = await page.query_selector_all('input[type="text"], input[type="url"]')
            for inp in inputs:
                ph = await inp.get_attribute("placeholder") or ""
                val = await inp.input_value() or ""
                if ("terms" in ph.lower() or "tos" in ph.lower()) and not val:
                    await inp.click()
                    await inp.fill(TERMS_URL)
                    print("  ✅ Terms of Service URL")
                    break
            else:
                # Try by surrounding label text
                tos = page.get_by_placeholder("Terms of Service", exact=False)
                if await tos.count() > 0:
                    await tos.first.fill(TERMS_URL)
                    print("  ✅ Terms of Service URL")
        except Exception as e:
            print(f"  ⚠  ToS: {e}")

        # ── Privacy Policy URL ─────────────────────────────────────────────
        try:
            inputs = await page.query_selector_all('input[type="text"], input[type="url"]')
            for inp in inputs:
                ph = await inp.get_attribute("placeholder") or ""
                val = await inp.input_value() or ""
                if "privacy" in ph.lower() and not val:
                    await inp.click()
                    await inp.fill(PRIVACY_URL)
                    print("  ✅ Privacy Policy URL")
                    break
        except Exception as e:
            print(f"  ⚠  Privacy: {e}")

        # ── Web/Desktop URL ───────────────────────────────────────────────
        try:
            inputs = await page.query_selector_all('input[type="text"], input[type="url"]')
            for inp in inputs:
                ph = await inp.get_attribute("placeholder") or ""
                val = await inp.input_value() or ""
                if ("https://" in ph or "website" in ph.lower() or "url" in ph.lower()) and not val:
                    await inp.click()
                    await inp.fill(WEBSITE_URL)
                    print("  ✅ Web/Desktop URL")
                    break
        except Exception as e:
            print(f"  ⚠  Web URL: {e}")

        # ── App Review Explanation ─────────────────────────────────────────
        try:
            textareas = await page.query_selector_all("textarea")
            for ta in textareas:
                val = await ta.input_value() or ""
                if len(val) < 10:
                    await ta.click()
                    await ta.fill(REVIEW_TEXT)
                    print("  ✅ App review explanation")
                    break
        except Exception as e:
            print(f"  ⚠  Review text: {e}")

        # ── Redirect URI (Login Kit) ───────────────────────────────────────
        try:
            inputs = await page.query_selector_all('input[type="text"], input[type="url"]')
            for inp in inputs:
                ph = await inp.get_attribute("placeholder") or ""
                val = await inp.input_value() or ""
                if ("redirect" in ph.lower() or "uri" in ph.lower() or "callback" in ph.lower()) and not val:
                    await inp.click()
                    await inp.fill(REDIRECT)
                    print("  ✅ Redirect URI")
                    # Click Add button if present
                    await page.wait_for_timeout(400)
                    add = page.get_by_role("button").filter(has_text="Add")
                    if await add.count() > 0:
                        await add.first.click()
                        await page.wait_for_timeout(600)
                    break
        except Exception as e:
            print(f"  ⚠  Redirect URI: {e}")

        # ── Screenshot final state ─────────────────────────────────────────
        await page.screenshot(path="/tmp/tt_filled.png", full_page=True)
        print("\n📸 Screenshot saved → /tmp/tt_filled.png")
        print("\n⚠  Still needed (manual):")
        print("   • Upload App Icon (1024x1024 PNG)")
        print("   • Upload Demo Video")
        print("   • Click Save")
        print("   • Add @bosskjames as Sandbox Test User under Login Kit → Manage")

        input("\n   Review the browser, then press ENTER to close: ")
        await browser.close()

    print("\n✅ Done. After saving, try: http://localhost:5050/api/tiktok/auth\n")


if __name__ == "__main__":
    asyncio.run(main())
