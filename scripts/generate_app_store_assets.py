#!/usr/bin/env python3
"""
Generate Shopify App Store icon + feature banner via DALL-E 3.

Outputs into app_store_assets/:
  - icon-1024.png     (1024x1024 — App Store wants 1200x1200; upscale offline)
  - banner-1792.png   (1792x1024 — App Store wants 1600x900; downscale + crop offline)
  - prompts.txt       (the exact prompts used, for reproducibility / iteration)

Usage:
  python3 scripts/generate_app_store_assets.py

Costs ~$0.16 (2 × DALL-E 3 HD images).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from core.cover_engine import dalle_generate

ASSETS_DIR = ROOT / "app_store_assets"
ASSETS_DIR.mkdir(exist_ok=True)


# Tuned for NarAI's brand: dark, premium, AI-aware, geometric
ICON_PROMPT = (
    "minimalist app icon design for an AI-powered Shopify product engine, "
    "centered glowing 'N' monogram in matte black metal with electric purple "
    "and cyan neon accents, premium 3D iconography, dark gradient background, "
    "sharp clean edges, suitable for a software icon at any size, high contrast, "
    "Apple App Store quality, 8k render, photorealistic"
)

BANNER_PROMPT = (
    "premium SaaS product hero banner showing the workflow of an AI product "
    "creation engine, on the left a Shopify storefront mockup on a dark surface "
    "with multiple polished product cards, on the right a holographic 3D "
    "visualization of four product photos materializing from glowing wireframes, "
    "subtle 'NarAI' wordmark in matte chrome, electric purple and cyan accent "
    "lighting, cinematic depth of field, dark professional background, "
    "16:9 wide composition, premium SaaS marketing aesthetic, 8k render"
)


def _save(local_path: str, target_name: str) -> Path:
    dest = ASSETS_DIR / target_name
    shutil.copy(local_path, dest)
    return dest


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set — load .env or export it first")

    print("Generating App Store assets via DALL-E 3...")
    print()

    # Icon — 1024x1024
    print("[1/2] Generating icon (1024x1024)...")
    icon = dalle_generate(ICON_PROMPT, size="1024x1024", quality="hd", style="vivid")
    if not icon.get("success"):
        print(f"  ✗ failed: {icon.get('error')}")
        return
    icon_path = _save(icon["local_path"], "icon-1024.png")
    print(f"  ✓ saved → {icon_path}")
    print(f"    hosted url: {icon.get('url')}")
    print()

    # Banner — 1792x1024 (closest 16:9)
    print("[2/2] Generating feature banner (1792x1024)...")
    banner = dalle_generate(BANNER_PROMPT, size="1792x1024", quality="hd", style="vivid")
    if not banner.get("success"):
        print(f"  ✗ failed: {banner.get('error')}")
        return
    banner_path = _save(banner["local_path"], "banner-1792.png")
    print(f"  ✓ saved → {banner_path}")
    print(f"    hosted url: {banner.get('url')}")
    print()

    # Save the prompts so future iterations are reproducible
    (ASSETS_DIR / "prompts.txt").write_text(
        f"# App Store asset prompts (generated {os.popen('date -u').read().strip()})\n\n"
        f"## ICON_PROMPT (1024x1024 hd vivid)\n{ICON_PROMPT}\n\n"
        f"## BANNER_PROMPT (1792x1024 hd vivid)\n{BANNER_PROMPT}\n"
    )
    print("Done. Next steps:")
    print(f"  1. Resize {icon_path.name} 1024→1200 (use Preview / `sips` / Photoshop)")
    print(f"  2. Resize+crop {banner_path.name} 1792x1024 → 1600x900 (preserve center)")
    print(f"  3. Take 3 screenshots of /admin/shopify, the install flow, and an installed merchant store")
    print(f"  4. Upload all to the Shopify App listing in Partner Dashboard")


if __name__ == "__main__":
    main()
