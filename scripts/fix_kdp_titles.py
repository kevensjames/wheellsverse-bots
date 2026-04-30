#!/usr/bin/env python3
"""Fix wrong book titles on KDP for two published books."""
import os, time, logging
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
log = logging.getLogger("fix_titles")

FIXES = [
    {
        "asin": "A2IAAK9I50XAEL",
        "genre": "historical",
        "old_title": "The Pharaoh's Architect: A Novel of Ancient Egypt, Power, and Impossible Dreams",
        "new_title": "Letters from the Trenches",
        "new_subtitle": "A World War I Historical Novel",
    },
    {
        "asin": "A1YCMKIZFWDKB4",
        "genre": "romance",
        "old_title": "Storm Watch: A Small Town Lighthouse Keeper Romance",
        "new_title": "One More Sunrise",
        "new_subtitle": "A Second Chance Romance",
    },
    {
        "asin": "AXC151YT2YGR7",
        "genre": "sci_fi",
        "old_title": "The Algorithm of God: When AI Discovers Mathematical Proof of Divine Existence",
        "new_title": "Parallel You",
        "new_subtitle": "A Mind-Bending Sci-Fi Thriller About Quantum Communication Across Universes",
    },
    {
        "asin": "A1EA7YK8USUA03",
        "genre": "self_help",
        "old_title": "Book Automation Millionaire: Let AI Do The Work While You Collect Passive Income in 2026",
        "new_title": "Broke to Bitcoin: The No-Nonsense Guide to Crypto for Working People",
        "new_subtitle": "",
    },
    {
        "asin": "ARMVY39EPNIOM",
        "genre": "true_crime",
        "old_title": "The Long Con: A True Crime-Inspired Thriller of Financial Deception and Community Betrayal",
        "new_title": "Dark Web Diaries: The Takedown of Marketplace X",
        "new_subtitle": "A True Crime Investigation",
    },
]

KDP_URL = "https://kdp.amazon.com"


def fix_title(page, asin: str, new_title: str, new_subtitle: str):
    details_url = f"{KDP_URL}/en_US/title-setup/kindle/{asin}/details"
    log.info("Navigating to details: %s", details_url)
    page.goto(details_url, wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)

    # Fill title
    for sel in ["#data-title", 'input[name="data[title]"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=5000):
                el.triple_click()
                el.fill(new_title)
                el.dispatch_event("input")
                el.dispatch_event("change")
                log.info("Title set: %s", new_title)
                break
        except Exception:
            continue

    # Fill subtitle if provided
    if new_subtitle:
        for sel in ["#data-subtitle", 'input[name="data[subtitle]"]']:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.triple_click()
                    el.fill(new_subtitle)
                    el.dispatch_event("input")
                    el.dispatch_event("change")
                    log.info("Subtitle set: %s", new_subtitle)
                    break
            except Exception:
                continue

    time.sleep(1)
    # Click Save & Continue
    for sel in ["button:has-text('Save and Continue')", "button:has-text('Save & Continue')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=5000):
                btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                time.sleep(3)
                log.info("Saved. URL: %s", page.url)
                return True
        except Exception:
            continue
    return False


def main():
    from playwright.sync_api import sync_playwright

    email = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, slow_mo=200)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        page.set_default_timeout(60000)

        # Login
        log.info("Logging in to KDP...")
        page.goto(f"{KDP_URL}/en_US/", wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        try:
            page.locator("a:has-text('Sign in'), a[href*='signin']").first.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
        except Exception:
            pass

        try:
            page.locator("#ap_email, input[type='email']").first.fill(email)
            page.locator("#continue, button:has-text('Continue')").first.click()
            time.sleep(2)
        except Exception:
            pass

        page.locator("#ap_password, input[type='password']").first.fill(password)
        page.locator("#signInSubmit, button[type='submit']").first.click()
        time.sleep(6)
        log.info("Logged in. URL: %s", page.url)

        # Fix each book
        for fix in FIXES:
            log.info("Fixing: %s → %s", fix["old_title"][:50], fix["new_title"])
            ok = fix_title(page, fix["asin"], fix["new_title"], fix["new_subtitle"])

            # Update local registry
            try:
                import json
                reg_path = ROOT / "data" / "kdp_registry.json"
                data = json.loads(reg_path.read_text())
                for e in data:
                    if e.get("title") == fix["old_title"] or (e.get("kdp_url", "") and fix["asin"] in e.get("kdp_url", "")):
                        e["title"] = fix["new_title"]
                        log.info("Registry updated: %s", fix["new_title"])
                reg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception as re:
                log.warning("Registry update failed: %s", re)

            status = "✅ Fixed" if ok else "⚠️ May need manual check"
            print(f"\n{status}: {fix['new_title']}")
            print(f"  KDP: {KDP_URL}/en_US/title-setup/kindle/{fix['asin']}/details")

        context.close()
        browser.close()

    print("\nDone. KDP may take a few minutes to reflect title changes.")


if __name__ == "__main__":
    main()
