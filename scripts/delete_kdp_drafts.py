#!/usr/bin/env python3
"""
scripts/delete_kdp_drafts.py
───────────────────────────────────────────────────────────────────────────────
Enumerate KDP bookshelf drafts and (optionally) delete one by item ID.

Reuses core.kdp_session.kdp_login_hardened, so the stored storage_state is
honored and password re-auth fires if needed. Runs visibly by default so the
operator can monitor the destructive step.

Usage:
  python scripts/delete_kdp_drafts.py --list
  python scripts/delete_kdp_drafts.py --delete 2J6CDQVM1FV
  python scripts/delete_kdp_drafts.py --delete-zombie  # 2J6CDQVM1FV shortcut
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [delete_drafts] %(levelname)s — %(message)s",
)
log = logging.getLogger("delete_drafts")

OUT_DIR = ROOT / "outputs" / "books"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ZOMBIE_ID = "2J6CDQVM1FV"
BOOKSHELF_URL = "https://kdp.amazon.com/en_US/bookshelf"


def _snap(page, label: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUT_DIR / f"kdp_delete_{label}_{ts}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log.info("Screenshot: %s", path.name)
    except Exception as e:
        log.warning("Screenshot %s failed: %s", label, e)
    return str(path)


def list_drafts(page) -> list[dict]:
    """Dump every visible draft on the bookshelf as {title, item_id, href}."""
    page.goto(BOOKSHELF_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)
    _snap(page, "bookshelf_before")

    # KDP renders bookshelf rows with various class patterns. Walk anything that
    # looks rowlike and find links containing an existing= or item= param plus
    # text suggesting "Draft" status.
    return page.evaluate(r"""() => {
        const seen = new Set();
        const out = [];
        // Cast a wide net: any link to a title-setup URL is anchored to a row.
        document.querySelectorAll('a[href*="title-setup"]').forEach(a => {
            const href = a.getAttribute('href') || '';
            const m = href.match(/[?&](?:existing|item)=([A-Z0-9]+)/);
            const id = m ? m[1] : null;
            if (!id || seen.has(id)) return;
            seen.add(id);
            // Walk up to the nearest tr/li/div that looks like a row container.
            let row = a;
            for (let i = 0; i < 8 && row && row.parentElement; i++) {
                row = row.parentElement;
                const rowText = (row.textContent || '');
                if (rowText.length > 200 || /tr|li/i.test(row.tagName)) break;
            }
            const rowText = (row?.textContent || '').trim();
            const isDraft = /draft/i.test(rowText);
            const titleEl = (row || a).querySelector('[class*="title" i], a, h2, h3, span');
            const title = (titleEl?.textContent || a.textContent || '').trim().slice(0, 120);
            out.push({
                id,
                title,
                href: href.slice(0, 260),
                is_draft: isDraft,
                row_text_sample: rowText.slice(0, 200),
            });
        });
        return out;
    }""")


def probe_draft(page, item_id: str) -> dict:
    """Check whether a draft is reachable via its direct title-setup URL."""
    url = f"https://kdp.amazon.com/en_US/title-setup/kindle/new/details?existing={item_id}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    final_url = page.url
    title = ""
    try:
        title_el = page.locator("#data-title").first
        if title_el.is_visible(timeout=2000):
            title = title_el.input_value() or ""
    except Exception:
        pass
    return {
        "probed_url": url,
        "final_url": final_url,
        "loaded_draft": "title-setup" in final_url and "/new/details" in final_url,
        "found_title": title,
    }


def delete_via_bookshelf_kebab(page, item_id: str) -> dict:
    """
    Find the bookshelf row for `item_id`, open its action menu, click
    'Delete draft', confirm the modal. Returns a status dict.
    """
    page.goto(BOOKSHELF_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)

    # Try multiple selector strategies — KDP rotates DOM structure occasionally.
    candidate_kebabs = [
        f"[data-asin='{item_id}'] [aria-label*='action' i]",
        f"[data-asin='{item_id}'] [aria-haspopup='true']",
        f"a[href*='{item_id}'] ~ * [aria-label*='action' i]",
        # Generic: the action menu near a link containing the item_id.
        f"xpath=//a[contains(@href, '{item_id}')]/ancestor::*[self::tr or self::li or self::div][1]//button[contains(@aria-label, 'action') or contains(@aria-label, 'menu') or @aria-haspopup='true']",
        f"xpath=//a[contains(@href, '{item_id}')]/ancestor::*[self::tr or self::li or self::div][1]//*[@role='button' and (contains(@aria-label, 'action') or contains(@aria-label, 'menu'))]",
    ]

    opened = False
    for sel in candidate_kebabs:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click()
                log.info("Opened kebab via: %s", sel)
                opened = True
                break
        except Exception as e:
            log.debug("Kebab selector failed (%s): %s", sel, e)
    if not opened:
        _snap(page, "kebab_not_found")
        return {"ok": False, "stage": "kebab_open",
                "message": "Could not open action menu for that row"}

    time.sleep(2)
    _snap(page, "kebab_open")

    # Click "Delete draft" / "Delete eBook" in the opened menu.
    delete_selectors = [
        "button:has-text('Delete draft')",
        "a:has-text('Delete draft')",
        "[role='menuitem']:has-text('Delete')",
        "button:has-text('Delete eBook')",
        "button:has-text('Delete book')",
        "li:has-text('Delete')",
    ]
    clicked_delete = False
    for sel in delete_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click()
                log.info("Clicked delete menu item via: %s", sel)
                clicked_delete = True
                break
        except Exception:
            continue
    if not clicked_delete:
        _snap(page, "delete_menuitem_not_found")
        return {"ok": False, "stage": "click_delete",
                "message": "Action menu opened but no Delete option found"}

    time.sleep(2)
    _snap(page, "delete_confirm_modal")

    # Confirmation dialog.
    confirm_selectors = [
        "button:has-text('Yes, delete')",
        "button:has-text('Delete draft')",  # may also be the confirm button label
        "button:has-text('Confirm')",
        "button:has-text('Yes')",
        "[role='dialog'] button:has-text('Delete')",
    ]
    confirmed = False
    for sel in confirm_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=4000):
                loc.click()
                log.info("Confirmed deletion via: %s", sel)
                confirmed = True
                break
        except Exception:
            continue
    if not confirmed:
        _snap(page, "confirm_not_found")
        return {"ok": False, "stage": "confirm",
                "message": "Delete clicked but confirmation dialog not handled"}

    time.sleep(5)
    _snap(page, "after_delete")
    return {"ok": True, "stage": "complete", "message": "Delete flow finished"}


def main() -> int:
    p = argparse.ArgumentParser(description="List/delete KDP drafts")
    p.add_argument("--list", action="store_true")
    p.add_argument("--delete", metavar="ITEM_ID")
    p.add_argument("--delete-zombie", action="store_true",
                   help=f"Shortcut for --delete {ZOMBIE_ID}")
    p.add_argument("--visible", action="store_true", default=True,
                   help="Open the browser visibly (default; destructive op safety)")
    p.add_argument("--headless", action="store_true",
                   help="Force headless (overrides --visible)")
    args = p.parse_args()

    item_id = args.delete or (ZOMBIE_ID if args.delete_zombie else None)
    headless = bool(args.headless)

    if not args.list and not item_id:
        p.error("Specify --list, --delete <ID>, or --delete-zombie")

    email = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")
    if not email or not password:
        log.error("KDP_EMAIL / KDP_PASSWORD missing in .env")
        return 2

    from playwright.sync_api import sync_playwright
    from core.kdp_session import (
        load_storage_state, kdp_login_hardened, is_authenticated,
        save_storage_state_if_authenticated, storage_state_path,
        fetch_otp_from_email,
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            slow_mo=300,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-web-security"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            storage_state=load_storage_state(),
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        # Auth via the hardened helper.
        auth = kdp_login_hardened(
            page=page, context=context, email=email, password=password,
            otp_fetcher=fetch_otp_from_email if os.getenv("KDP_OTP_EMAIL") else None,
            screenshot_dir=str(OUT_DIR), logger=log,
        )
        if not auth["ok"]:
            log.error("Auth failed: %s", auth["message"])
            return 3
        save_storage_state_if_authenticated(context, page, str(storage_state_path()))

        # List phase — always run so we have a baseline + verification.
        drafts = list_drafts(page)
        log.info("Enumerated %d draft-row candidates", len(drafts))
        for d in drafts:
            log.info("  %s  draft=%s  id=%s  title=%r",
                     "[ZOMBIE]" if d["id"] == ZOMBIE_ID else "        ",
                     d["is_draft"], d["id"], d["title"][:80])

        result = {"drafts_seen": drafts}

        # Probe the target ID before attempting the UI delete — fastest signal.
        if item_id:
            probe_before = probe_draft(page, item_id)
            log.info("Probe BEFORE delete: %s", json.dumps(probe_before, default=str))
            result["probe_before"] = probe_before

            if not probe_before["loaded_draft"]:
                log.info("Draft %s already gone (probe URL did not load a wizard)", item_id)
                result["status"] = "already_gone"
            else:
                log.info("Draft %s is live; attempting UI delete", item_id)
                delete_result = delete_via_bookshelf_kebab(page, item_id)
                log.info("Delete attempt result: %s", json.dumps(delete_result, default=str))
                result["delete_result"] = delete_result

                # Probe again to verify.
                time.sleep(3)
                probe_after = probe_draft(page, item_id)
                log.info("Probe AFTER delete: %s", json.dumps(probe_after, default=str))
                result["probe_after"] = probe_after
                result["status"] = "deleted" if not probe_after["loaded_draft"] else "still_present"

        log.info("FINAL RESULT: %s", json.dumps(result, default=str)[:2000])
        time.sleep(2)
        context.close()
        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
