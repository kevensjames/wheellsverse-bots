#!/usr/bin/env python3
"""
core/cover_engine.py
─────────────────────────────────────────────────────────────────────────────
NarAI Cover Image Generation Engine

Supports:
  • DALL·E 3 (OpenAI)   — premium, prompt-accurate, 1024×1024 / 1792×1024
  • Leonardo AI          — fine-tuned models, high quality, free tier available

NarAI tries DALL·E 3 first (better prompt adherence for text-on-image),
falls back to Leonardo AI if DALL·E is unavailable.

Midjourney has NO public API — NarAI generates the prompt and saves it
for manual use. The prompt is included in every product package.

Output:
  • PNG saved to outputs/covers/{platform}/{safe_title}_{ts}.png
  • Returns dict with local_path, url, source, and midjourney_prompt
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

log = logging.getLogger("cover_engine")

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
COVERS_DIR = ROOT / "outputs" / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

# ── Keys ──────────────────────────────────────────────────────────────────────
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
LEONARDO_KEY = os.getenv("LEONARDO_API_KEY", "")

# Leonardo model IDs (updated April 2026)
LEONARDO_MODELS = {
    "default": "b24e16ff-06e3-43eb-8d33-4416c2d75876",  # Leonardo Diffusion XL
    "photoreal": "5c232a9e-9061-4777-980a-ddc8e65647c6",  # PhotoReal v2
    "creative": "6bef9f1b-29cb-40c7-b9df-32b51c1f67d3",  # Leonardo Creative
}

POLL_INTERVAL = 5   # seconds between Leonardo status polls
POLL_MAX = 60  # max polls (~5 minutes)


# ══════════════════════════════════════════════════════════════════════════════
# DALL·E 3
# ══════════════════════════════════════════════════════════════════════════════

def dalle_generate(
    prompt: str,
    size: str = "1024x1792",   # portrait — ideal for ebook covers
    quality: str = "hd",
    style: str = "vivid",
) -> dict:
    """
    Generate a cover image with DALL·E 3 via OpenAI API.

    Args:
        prompt:  Full image generation prompt
        size:    '1024x1024' | '1024x1792' (portrait) | '1792x1024' (landscape)
        quality: 'standard' | 'hd'
        style:   'vivid' | 'natural'

    Returns:
        {success, url, local_path, revised_prompt, source, error}
    """
    if not OPENAI_KEY:
        return {"success": False, "error": "OPENAI_API_KEY not set", "source": "dalle"}

    try:
        import openai
    except ImportError:
        # Fallback to raw HTTP if openai package not installed
        return _dalle_raw_http(prompt, size, quality, style)

    try:
        client = openai.OpenAI(api_key=OPENAI_KEY)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt[:4000],
            size=size,
            quality=quality,
            style=style,
            n=1,
        )
        image_url = response.data[0].url
        revised_prompt = getattr(response.data[0], "revised_prompt", prompt)
        local_path = _download_image(image_url, prefix="dalle")

        log.info(f"[CoverEngine] DALL·E 3 ✅ → {local_path.name}")
        return {
            "success": True,
            "url": image_url,
            "local_path": str(local_path),
            "revised_prompt": revised_prompt,
            "source": "dalle3",
            "error": "",
        }

    except Exception as e:
        log.warning(f"[CoverEngine] DALL·E 3 error: {e}")
        return {"success": False, "error": str(e), "source": "dalle"}


def _dalle_raw_http(prompt: str, size: str, quality: str, style: str) -> dict:
    """DALL·E 3 via raw HTTP — no openai package required."""
    try:
        body = json.dumps({
            "model": "dall-e-3",
            "prompt": prompt[:4000],
            "size": size,
            "quality": quality,
            "style": style,
            "n": 1,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/images/generations",
            data=body,
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())

        image_url = data["data"][0]["url"]
        revised_prompt = data["data"][0].get("revised_prompt", prompt)
        local_path = _download_image(image_url, prefix="dalle")

        log.info(f"[CoverEngine] DALL·E 3 (raw HTTP) ✅ → {local_path.name}")
        return {
            "success": True,
            "url": image_url,
            "local_path": str(local_path),
            "revised_prompt": revised_prompt,
            "source": "dalle3",
            "error": "",
        }

    except Exception as e:
        log.warning(f"[CoverEngine] DALL·E 3 raw HTTP error: {e}")
        return {"success": False, "error": str(e), "source": "dalle"}


# ══════════════════════════════════════════════════════════════════════════════
# LEONARDO AI
# ══════════════════════════════════════════════════════════════════════════════

def leonardo_generate(
    prompt: str,
    negative_prompt: str = "text, words, letters, blurry, low quality, watermark",
    model_key: str = "default",
    width: int = 832,
    height: int = 1216,    # 2:3 portrait — ebook cover ratio
    num_images: int = 1,
    guidance_scale: int = 7,
    num_inference_steps: int = 30,
) -> dict:
    """
    Generate a cover image with Leonardo AI.

    Args:
        prompt:          Full generation prompt
        negative_prompt: What to avoid in the image
        model_key:       'default' | 'photoreal' | 'creative'
        width / height:  Output dimensions (must be multiples of 8)

    Returns:
        {success, url, local_path, generation_id, source, error}
    """
    if not LEONARDO_KEY:
        return {"success": False, "error": "LEONARDO_API_KEY not set", "source": "leonardo"}

    model_id = LEONARDO_MODELS.get(model_key, LEONARDO_MODELS["default"])
    headers = {
        "Authorization": f"Bearer {LEONARDO_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # ── Submit generation ─────────────────────────────────────────────────────
    try:
        payload = {
            "prompt": prompt[:1500],
            "negative_prompt": negative_prompt,
            "modelId": model_id,
            "width": width,
            "height": height,
            "num_images": num_images,
            "guidance_scale": guidance_scale,
            "num_inference_steps": num_inference_steps,
            "presetStyle": "LEONARDO",
            "public": False,
        }

        req = urllib.request.Request(
            "https://cloud.leonardo.ai/api/rest/v1/generations",
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())

        generation_id = (
            data.get("sdGenerationJob", {}).get("generationId")
            or data.get("generationId", "")
        )
        if not generation_id:
            return {
                "success": False,
                "error": f"Leonardo: no generation ID returned — {data}",
                "source": "leonardo",
            }

        log.info(f"[CoverEngine] Leonardo generation submitted: {generation_id}")

    except Exception as e:
        log.warning(f"[CoverEngine] Leonardo submit error: {e}")
        return {"success": False, "error": str(e), "source": "leonardo"}

    # ── Poll for result ───────────────────────────────────────────────────────
    for attempt in range(POLL_MAX):
        time.sleep(POLL_INTERVAL)
        try:
            poll_req = urllib.request.Request(
                f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}",
                headers={k: v for k, v in headers.items() if k != "Content-Type"},
            )
            with urllib.request.urlopen(poll_req, timeout=15) as r:
                poll_data = json.loads(r.read())

            gen_info = poll_data.get("generations_by_pk", {})
            status = gen_info.get("status", "")

            if status == "COMPLETE":
                images = gen_info.get("generated_images", [])
                if not images:
                    return {
                        "success": False,
                        "error": "Leonardo: generation complete but no images",
                        "source": "leonardo",
                    }
                image_url = images[0].get("url", "")
                local_path = _download_image(image_url, prefix="leonardo")
                log.info(f"[CoverEngine] Leonardo ✅ ({attempt + 1} polls) → {local_path.name}")
                return {
                    "success": True,
                    "url": image_url,
                    "local_path": str(local_path),
                    "generation_id": generation_id,
                    "source": "leonardo",
                    "error": "",
                }

            elif status == "FAILED":
                return {
                    "success": False,
                    "error": f"Leonardo generation failed: {gen_info}",
                    "source": "leonardo",
                }

            log.debug(f"[CoverEngine] Leonardo poll {attempt + 1}: status={status}")

        except Exception as poll_err:
            log.debug(f"[CoverEngine] Leonardo poll error (attempt {attempt + 1}): {poll_err}")

    return {
        "success": False,
        "error": f"Leonardo timed out after {POLL_MAX * POLL_INTERVAL}s",
        "source": "leonardo",
    }


# ══════════════════════════════════════════════════════════════════════════════
# MASTER GENERATE — tries DALL·E → Leonardo → saves prompt for Midjourney
# ══════════════════════════════════════════════════════════════════════════════

def generate_cover(
    cover_prompts: dict,
    platform: str,
    title: str,
    product_type: str = "ebook",
) -> dict:
    """
    Auto-generate a product cover. Priority:
      1. DALL·E 3       (if OPENAI_API_KEY set)
      2. Leonardo AI     (if LEONARDO_API_KEY set)
      3. Save prompts    (for manual Midjourney/Canva use)

    Args:
        cover_prompts:  Output from build_cover_design_prompt() — contains
                        'dalle', 'midjourney', 'leonardo', 'dimensions' keys
        platform:       'gumroad' | 'etsy' | 'payhip' | 'amazon_kdp'
        title:          Product title (used for filename)
        product_type:   Affects size selection

    Returns:
        {
          success, source, local_path, url,
          midjourney_prompt,   ← always present for manual use
          canva_search,        ← always present for manual use
          error
        }
    """
    dalle_prompt = cover_prompts.get("dalle", "")
    leo_prompt = cover_prompts.get("leonardo", "")
    mj_prompt = cover_prompts.get("midjourney", "")
    canva_search = cover_prompts.get("canva_search", "")

    # Choose dimensions based on platform/type
    size_dalle, leo_w, leo_h = _get_dimensions(platform, product_type)

    result_base = {
        "midjourney_prompt": mj_prompt,
        "canva_search": canva_search,
        "title": title,
        "platform": platform,
    }

    # ── Try DALL·E 3 ──────────────────────────────────────────────────────────
    if OPENAI_KEY and dalle_prompt:
        log.info(f"[CoverEngine] Trying DALL·E 3 for '{title}'…")
        result = dalle_generate(
            prompt=_enrich_prompt(dalle_prompt, title, platform),
            size=size_dalle,
            quality="hd",
            style="vivid",
        )
        if result.get("success"):
            _move_to_platform_dir(result, platform, title)
            return {**result_base, **result}
        log.warning(f"[CoverEngine] DALL·E 3 failed → trying Leonardo: {result.get('error')}")

    # ── Try Leonardo AI ───────────────────────────────────────────────────────
    if LEONARDO_KEY and leo_prompt:
        log.info(f"[CoverEngine] Trying Leonardo AI for '{title}'…")
        model_key = "photoreal" if platform in ("amazon_kdp", "payhip") else "default"
        result = leonardo_generate(
            prompt=_enrich_prompt(leo_prompt, title, platform),
            negative_prompt=(
                "text, words, letters, blurry, pixelated, low quality, "
                "watermark, signature, frame, border"
            ),
            model_key=model_key,
            width=leo_w,
            height=leo_h,
        )
        if result.get("success"):
            _move_to_platform_dir(result, platform, title)
            return {**result_base, **result}
        log.warning(f"[CoverEngine] Leonardo failed → manual mode: {result.get('error')}")

    # ── No API available — return prompts for manual generation ───────────────
    log.info("[CoverEngine] No image API available — prompts saved for manual use")
    return {
        **result_base,
        "success": False,
        "source": "manual",
        "local_path": "",
        "url": "",
        "error": "No image API key configured. Use the Midjourney prompt or Canva to create the cover manually.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_dimensions(platform: str, product_type: str) -> tuple[str, int, int]:
    """
    Return (dalle_size, leo_width, leo_height) per platform.
    All Leonardo dimensions must be multiples of 8.
    """
    if platform == "amazon_kdp":
        # KDP standard: 6×9 inches → portrait
        return "1024x1792", 832, 1216

    if product_type in ("printable", "planner", "journal_template", "tracker"):
        # US Letter portrait
        return "1024x1792", 832, 1216

    if platform == "etsy":
        # Etsy thumbnail: square or slight portrait
        return "1024x1024", 1024, 1024

    # Default: portrait ebook cover (2:3 ratio)
    return "1024x1792", 832, 1216


def _enrich_prompt(prompt: str, title: str, platform: str) -> str:
    """
    Add platform-specific quality boosters to the prompt.
    DALL·E 3 does better with explicit quality descriptors.
    """
    platform_notes = {
        "gumroad": "digital product cover, professional design, clean white space for text overlay",
        "etsy": "digital product mockup, clean background, Etsy marketplace style",
        "payhip": "digital download cover, professional, clean typography space",
        "amazon_kdp": "book cover, Amazon Kindle, professional publishing, bestseller quality",
    }
    note = platform_notes.get(platform, "digital product cover, professional design")
    # Add to end of prompt if it doesn't already contain these terms
    if "professional" not in prompt.lower():
        prompt = f"{prompt}, {note}"
    return prompt[:2000]


def _download_image(url: str, prefix: str = "cover") -> Path:
    """Download an image URL and save to COVERS_DIR. Returns Path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.png"
    dest = COVERS_DIR / filename

    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            dest.write_bytes(r.read())
    except Exception as e:
        log.warning(f"[CoverEngine] Download failed: {e}")
        dest.write_bytes(b"")   # placeholder so path is valid

    return dest


def _move_to_platform_dir(result: dict, platform: str, title: str):
    """
    Move the downloaded cover into outputs/covers/{platform}/ with a clean name.
    Updates result dict in place.
    """
    src_path = Path(result.get("local_path", ""))
    if not src_path.exists() or src_path.stat().st_size == 0:
        return

    import re
    safe_title = re.sub(r"[^a-zA-Z0-9_]", "_", title[:35])
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    dest_dir = COVERS_DIR / platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{safe_title}_{ts}.png"

    try:
        src_path.rename(dest_path)
        result["local_path"] = str(dest_path)
    except Exception:
        # rename across filesystems fails — copy instead
        import shutil
        shutil.copy2(src_path, dest_path)
        src_path.unlink(missing_ok=True)
        result["local_path"] = str(dest_path)


def get_available_engines() -> dict:
    """Return which image engines are configured."""
    return {
        "dalle": bool(OPENAI_KEY),
        "leonardo": bool(LEONARDO_KEY),
        "any": bool(OPENAI_KEY or LEONARDO_KEY),
    }
