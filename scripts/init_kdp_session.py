#!/usr/bin/env python3
"""
scripts/init_kdp_session.py
───────────────────────────────────────────────────────────────────────────────
One-time interactive KDP login. Captures cookies + localStorage to a
storage_state JSON file that Railway (or any unattended runner) can mount as
a volume so subsequent runs skip the entire login dance.

Run this on your Mac once with a visible browser:

  .venv/bin/python scripts/init_kdp_session.py

You will:
  1. See a Chromium window open at kdp.amazon.com
  2. Sign in manually, complete any 2FA prompt
  3. Land on the KDP Bookshelf
  4. Press Enter in this terminal — the script saves storage_state.json

Output path (controlled by env $KDP_STORAGE_STATE, default below):
  data/.kdp_storage_state.json

After capture, upload the file to your Railway volume:
  railway run cp data/.kdp_storage_state.json /mnt/kdp-state/

Or use the Railway Volume web UI to drop the file in.

Re-run this script when KDP forces re-auth (cookies typically last ~30 days).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from core.kdp_session import storage_state_path  # noqa: E402


def main() -> int:
    out = storage_state_path()
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nKDP storage_state target: {out}\n")
    print("Opening Chromium — sign in manually and complete any 2FA, then return here.\n")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed in this venv. Run:")
        print("  .venv/bin/pip install playwright && .venv/bin/playwright install chromium")
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=100)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = ctx.new_page()
        page.goto("https://kdp.amazon.com/en_US/", wait_until="domcontentloaded", timeout=60000)

        print("\nWhen you can see the KDP Bookshelf in the browser window,")
        print("press Enter here to capture cookies and exit.\n")
        try:
            input("Press Enter to save → ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted; nothing saved.")
            browser.close()
            return 1

        try:
            ctx.storage_state(path=str(out))
        except Exception as e:
            print(f"Save failed: {e}")
            browser.close()
            return 1

        browser.close()

    size = out.stat().st_size if out.exists() else 0
    print(f"\nSaved {size:,} bytes to {out}")
    print("Next step: upload this file to your Railway volume mount path.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
