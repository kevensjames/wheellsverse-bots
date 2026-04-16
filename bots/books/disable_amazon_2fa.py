#!/usr/bin/env python3
"""Disable Amazon 2FA via Playwright. One-time use."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # noqa: E402

EMAIL = os.getenv("KDP_EMAIL", "")
PASSWORD = os.getenv("KDP_PASSWORD", "")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        page = browser.new_page()

        # 1. Sign in to Amazon
        print("Opening Amazon sign-in...")
        page.goto("https://www.amazon.com/gp/sign-in.html", wait_until="networkidle", timeout=60000)
        time.sleep(3)
        print("Landed on:", page.url)
        print("Page title:", page.title())

        # Find email input — try multiple selectors
        email_sel = None
        for sel in ["#ap_email", "input[name='email']", "input[type='email']", "input[name='username']"]:
            try:
                page.wait_for_selector(sel, timeout=5000)
                email_sel = sel
                print(f"Found email field: {sel}")
                break
            except Exception:
                continue

        if not email_sel:
            # Dump all input fields to debug
            inputs = page.eval_on_selector_all("input", "els => els.map(e => ({id:e.id, name:e.name, type:e.type}))")
            print("All inputs on page:", inputs)
            browser.close()
            return

        page.fill(email_sel, EMAIL)
        # Click continue/next button
        for btn in ["#continue", "input[type='submit']", "button[type='submit']"]:
            try:
                page.click(btn, timeout=3000)
                break
            except Exception:
                continue
        time.sleep(2)

        # Password field
        for pwd_sel in ["#ap_password", "input[name='password']", "input[type='password']"]:
            try:
                page.wait_for_selector(pwd_sel, timeout=5000)
                page.fill(pwd_sel, PASSWORD)
                print(f"Found password field: {pwd_sel}")
                break
            except Exception:
                continue

        # Submit
        for btn in ["#signInSubmit", "input[type='submit']", "button[type='submit']"]:
            try:
                page.click(btn, timeout=3000)
                break
            except Exception:
                continue

        # 2. Handle 2FA prompt — user must enter code manually
        print("\n⚠️  Enter your 2FA code in the browser window NOW.")
        print("Waiting up to 90 seconds...")
        try:
            page.wait_for_url("https://www.amazon.com/**", timeout=90000)
            print("✅ Signed in.")
        except PWTimeout:
            print("Still on MFA page — waiting a bit longer...")
            time.sleep(10)

        # 3. Navigate to Login & Security settings
        print("Navigating to Login & Security...")
        page.goto("https://www.amazon.com/gp/css/account/info/view.html")
        time.sleep(2)
        page.goto("https://www.amazon.com/ap/cnep/workflows/mfa/disable")
        time.sleep(2)

        print("Current URL:", page.url)

        # Try to find and click the disable/turn off button
        disabled = False
        for selector in [
            "input[value*='Turn off']",
            "button:has-text('Turn off')",
            "a:has-text('Turn off')",
            "input[value*='Disable']",
            "button:has-text('Disable')",
            "[data-action='disable']",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=3000):
                    el.click()
                    time.sleep(2)
                    print(f"✅ Clicked disable via: {selector}")
                    disabled = True
                    break
            except Exception:
                continue

        if not disabled:
            # Fallback: go to account security page and look around
            page.goto("https://www.amazon.com/a/settings/approval")
            time.sleep(3)
            print("URL after fallback nav:", page.url)
            for selector in [
                "button:has-text('Turn off')",
                "button:has-text('Disable')",
                "a:has-text('Turn off')",
                "span:has-text('Turn off')",
            ]:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        time.sleep(2)
                        print(f"✅ Clicked via fallback: {selector}")
                        disabled = True
                        break
                except Exception:
                    continue

        if not disabled:
            print("\n⚠️  Could not auto-click the disable button.")
            print("The browser is open — please click 'Turn off' manually in the window.")
            print("Then press ENTER here when done.")
            input()
        else:
            # Confirm any confirmation dialog
            for confirm in [
                "button:has-text('Turn off')",
                "button:has-text('Confirm')",
                "button:has-text('Yes')",
                "input[value='Turn off']",
            ]:
                try:
                    el = page.locator(confirm).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        time.sleep(2)
                        print(f"✅ Confirmed via: {confirm}")
                        break
                except Exception:
                    continue

        time.sleep(2)
        print("Final URL:", page.url)
        print("\n✅ Done. 2FA should now be disabled on your Amazon account.")
        print("You can close the browser.")
        input("Press ENTER to close browser...")
        browser.close()


if __name__ == "__main__":
    run()
