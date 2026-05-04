#!/usr/bin/env python3
"""
scripts/generate_shop_assets.py
─────────────────────────────────────────────────────────────────────────────
One-shot brand-asset renderer for the @shop.wheellsverse Meta pair.

Renders 3 DALL-E HD backgrounds (no text overlay — clean brand art):
  - avatar.jpg              (1080x1080, profile picture for IG + FB)
  - fb_cover.jpg            (1640x924,  Facebook Page header)
  - ig_story_banner.jpg     (1080x1920, source for IG highlight covers)

Outputs are moved into outputs/social_images/shop/ for clean organization.

Cost: ~3 × DALL-E 3 HD = ~$0.36 in OpenAI credits.

Run: python3 scripts/generate_shop_assets.py
─────────────────────────────────────────────────────────────────────────────
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.social_image import generate_social_image, OUTPUT_DIR

SHOP_DIR = OUTPUT_DIR / "shop"
SHOP_DIR.mkdir(parents=True, exist_ok=True)

# Brand-locked style hint: matches neural-mesh theme palette in
# themes/neural-mesh/config/settings_data.json (cyan #00d4ff + gold #ffd700 on
# deep navy #080b11). Composition cues vary per platform aspect ratio.
_BASE_STYLE = (
    "Premium WheellsVerse brand visual. Deep navy and indigo background "
    "(#080b11 base), bright cyan (#00d4ff) and warm gold (#ffd700) accent "
    "highlights, abstract neural-mesh lattice with glowing nodes and "
    "filaments, soft volumetric lighting, futuristic AI commerce aesthetic, "
    "ultra-clean minimal composition. No text, no letters, no logos, no "
    "watermarks. 8k commercial quality, ultra-sharp."
)

# (platform, creative-theme, output filename, composition cue)
_ASSETS = [
    ("profile_avatar",
     "Centered glowing neural mesh emblem, perfect symmetry, focal core",
     "avatar.jpg",
     "Subject centered, generous breathing room around edges (square crop)."),
    ("facebook_cover",
     "Panoramic neural mesh tapestry flowing left to right",
     "fb_cover.jpg",
     "Horizontal flow, focal interest off-center-right (wide aspect)."),
    ("instagram_story_banner",
     "Vertical neural cascade rising from base to apex",
     "ig_story_banner.jpg",
     "Vertical flow, layered depth top to bottom (tall aspect)."),
]


def main() -> int:
    print(f"Rendering 3 brand assets to {SHOP_DIR}/")
    print(f"(~$0.36 DALL-E HD spend — Ctrl-C now to abort)\n")

    failures = []
    for platform, theme, fname, composition in _ASSETS:
        print(f"→ {fname}  ({platform})")
        local = generate_social_image(
            headline=theme,            # used as DALL-E creative direction, NOT rendered
            subtext="",
            platform=platform,
            style_hint=f"{_BASE_STYLE} {composition}",
        )
        if not local:
            print(f"  ✗ Failed (DALL-E error or OPENAI_API_KEY missing)")
            failures.append(fname)
            continue
        dest = SHOP_DIR / fname
        shutil.move(str(local), str(dest))
        print(f"  ✓ {dest}")

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print(f"All 3 assets ready in {SHOP_DIR}/")
    print("Upload during phone-side Meta signup (see plan step 1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
