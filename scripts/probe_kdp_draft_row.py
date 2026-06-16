#!/usr/bin/env python3
"""
scripts/probe_kdp_draft_row.py
───────────────────────────────────────────────────────────────────────────────
Dump everything KDP's bookshelf renders around a specific item_id so we can
write accurate delete selectors.

Output: log lines with element snapshots + a fresh screenshot per discovery.

Usage:
  python scripts/probe_kdp_draft_row.py 2J6CDQVM1FV
"""
from __future__ import annotations
import json, logging, os, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [probe] %(levelname)s — %(message)s")
log = logging.getLogger("probe")

OUT = ROOT / "outputs" / "books"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: probe_kdp_draft_row.py <ITEM_ID>")
        return 2
    item_id = sys.argv[1]

    email = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")
    if not email or not password:
        log.error("KDP_EMAIL / KDP_PASSWORD missing")
        return 2

    from playwright.sync_api import sync_playwright
    from core.kdp_session import (
        load_storage_state, kdp_login_hardened,
        save_storage_state_if_authenticated, storage_state_path,
        fetch_otp_from_email,
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=300,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-web-security"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
            locale="en-US", timezone_id="America/New_York",
            storage_state=load_storage_state(),
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        page.set_default_timeout(60000)

        auth = kdp_login_hardened(
            page=page, context=context, email=email, password=password,
            otp_fetcher=fetch_otp_from_email if os.getenv("KDP_OTP_EMAIL") else None,
            screenshot_dir=str(OUT), logger=log)
        if not auth["ok"]:
            log.error("Auth failed: %s", auth["message"])
            return 3
        save_storage_state_if_authenticated(context, page, str(storage_state_path()))

        page.goto("https://kdp.amazon.com/en_US/bookshelf",
                  wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        page.screenshot(path=str(OUT / f"kdp_probe_bookshelf_{ts}.png"), full_page=True)

        # 1) Find every element whose attributes or text mention the item_id.
        hits = page.evaluate(r"""(id) => {
            const out = [];
            const all = document.querySelectorAll('*');
            for (let i = 0; i < all.length && out.length < 40; i++) {
                const el = all[i];
                let hit = false;
                for (const attr of el.attributes || []) {
                    if (attr.value && attr.value.includes(id)) { hit = true; break; }
                }
                if (!hit && (el.textContent || '').includes(id) && el.children.length === 0) hit = true;
                if (hit) {
                    out.push({
                        tag: el.tagName,
                        id: el.id || '',
                        cls: (el.className && el.className.toString) ? el.className.toString().slice(0,120) : '',
                        attrs: Array.from(el.attributes || []).map(a => `${a.name}=${a.value.slice(0,80)}`),
                        text: (el.textContent || '').trim().slice(0, 80),
                        outerHTML_head: el.outerHTML.slice(0, 240),
                    });
                }
            }
            return out;
        }""", item_id)
        log.info("=== Elements referencing %s: %d hits ===", item_id, len(hits))
        for i, h in enumerate(hits):
            log.info("HIT[%d] tag=%s id=%s cls=%s text=%r", i, h["tag"], h["id"], h["cls"][:80], h["text"])
            log.info("  attrs: %s", h["attrs"][:8])
            log.info("  outerHTML[:240]: %s", h["outerHTML_head"])

        # 2) Walk up from the first hit, dump the row container's outerHTML.
        row_info = page.evaluate(r"""(id) => {
            // Find the first element with id in attribute or as direct text.
            let anchor = null;
            for (const el of document.querySelectorAll('*')) {
                let hit = false;
                for (const a of el.attributes || []) if (a.value && a.value.includes(id)) { hit = true; break; }
                if (hit) { anchor = el; break; }
            }
            if (!anchor) return null;
            // Walk up until we find a rowlike container (heuristics).
            let row = anchor;
            for (let i = 0; i < 12 && row && row.parentElement; i++) {
                row = row.parentElement;
                if (/tr|li/i.test(row.tagName)) break;
                const rect = row.getBoundingClientRect();
                if (rect.width > 600 && rect.height > 80 && rect.height < 400) break;
            }
            return {
                anchor_tag: anchor.tagName,
                anchor_html: anchor.outerHTML.slice(0, 400),
                row_tag: row?.tagName || '',
                row_cls: (row?.className && row.className.toString) ? row.className.toString().slice(0,200) : '',
                row_html: row?.outerHTML?.slice(0, 2500) || '',
                row_buttons: Array.from(row?.querySelectorAll('button, a, [role="button"]') || []).map(b => ({
                    tag: b.tagName, text: (b.textContent||'').trim().slice(0,60),
                    aria: b.getAttribute('aria-label') || '',
                    haspopup: b.getAttribute('aria-haspopup') || '',
                    cls: (b.className && b.className.toString) ? b.className.toString().slice(0,80) : '',
                })),
            };
        }""", item_id)
        log.info("=== Row walkup for %s ===", item_id)
        if not row_info:
            log.warning("Row not found in DOM — bookshelf may not show this draft directly.")
        else:
            log.info("ANCHOR tag=%s", row_info["anchor_tag"])
            log.info("ANCHOR html: %s", row_info["anchor_html"])
            log.info("ROW tag=%s cls=%s", row_info["row_tag"], row_info["row_cls"][:160])
            log.info("ROW html[:2500]: %s", row_info["row_html"])
            log.info("ROW buttons count=%d", len(row_info["row_buttons"]))
            for b in row_info["row_buttons"]:
                log.info("  BTN %s", json.dumps(b))

        # 3) Try to scroll the bookshelf to load all rows (KDP sometimes paginates).
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)
        page.screenshot(path=str(OUT / f"kdp_probe_bookshelf_scrolled_{ts}.png"), full_page=True)

        # 4) Search the URL for menu/popover triggers anywhere on page.
        global_menus = page.evaluate(r"""() => {
            const out = [];
            document.querySelectorAll('[aria-haspopup="true"], [aria-expanded], [role="menu"], [class*="kebab" i], [class*="dropdown" i]').forEach(el => {
                if (out.length > 40) return;
                if (el.offsetParent === null) return;  // hidden
                out.push({
                    tag: el.tagName,
                    aria_label: el.getAttribute('aria-label') || '',
                    aria_haspopup: el.getAttribute('aria-haspopup') || '',
                    role: el.getAttribute('role') || '',
                    cls: (el.className && el.className.toString) ? el.className.toString().slice(0,100) : '',
                });
            });
            return out;
        }""")
        log.info("=== Visible popup/menu triggers on page: %d ===", len(global_menus))
        for m in global_menus[:20]:
            log.info("  MENU %s", json.dumps(m))

        time.sleep(2)
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
