#!/usr/bin/env python3
"""
core/media_engine.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Media Engine — Auto-generate product covers, 3D mockups, and
video animations for every Shopify product and upload them automatically.

Backends (each falls back gracefully):
  Images:  DALL·E 3  →  Leonardo AI  →  skip
  3D:      Leonardo AI (3D preset)  →  DALL·E 3 (3D prompt)  →  skip
  Video:   Runway ML Gen-3  →  Luma AI Dream Machine  →  skip

Upload:
  Photos → POST /products/{id}/images.json
  Videos → POST /products/{id}/media.json  (Shopify 2021-01+)

Usage:
  from core.media_engine import generate_full_media_pack, upload_media_pack_to_shopify
  pack   = generate_full_media_pack(product_data)   # returns {covers, mockup_3d, video, all_media}
  result = upload_media_pack_to_shopify(product_id, pack)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("media_engine")

# ── API Keys ──────────────────────────────────────────────────────────────────
OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")
LEONARDO_KEY = os.getenv("LEONARDO_API_KEY", "")
RUNWAY_KEY   = os.getenv("RUNWAY_API_KEY", "")
LUMA_KEY     = os.getenv("LUMAAI_API_KEY", "")

# ── Endpoints ─────────────────────────────────────────────────────────────────
DALLE_URL    = "https://api.openai.com/v1/images/generations"
LEONARDO_URL = "https://cloud.leonardo.ai/api/rest/v1"
RUNWAY_URL   = "https://api.runwayml.com/v1"
LUMA_URL     = "https://api.lumalabs.ai/dream-machine/v1"

# Leonardo AI style UUIDs
_LEO_3D_STYLE   = "debdf72a-91d4-4e7d-8c3b-0c0fe47c2908"   # 3D Render
_LEO_PROMO_STYLE = "111dc692-d470-4eec-b791-3475abac4673"   # Product Photography


# ─── Image backends ──────────────────────────────────────────────────────────

def _dalle3(prompt: str, size: str = "1024x1024", quality: str = "standard") -> Optional[str]:
    """Generate one image with DALL·E 3. Returns URL or None."""
    if not OPENAI_KEY:
        return None
    try:
        import urllib.request
        body = json.dumps({
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "url",
        }).encode()
        req = urllib.request.Request(
            DALLE_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        url = data.get("data", [{}])[0].get("url")
        log.info(f"[MediaEngine] DALL·E 3 → {url[:60] if url else 'None'}")
        return url
    except Exception as e:
        log.warning(f"[MediaEngine] DALL·E 3 error: {e}")
        return None


def _leonardo(prompt: str, style_uuid: str = None, width: int = 1024, height: int = 1024) -> Optional[str]:
    """Generate one image with Leonardo AI. Polls until ready (max ~60 s)."""
    if not LEONARDO_KEY:
        return None
    try:
        import urllib.request
        headers = {
            "Authorization": f"Bearer {LEONARDO_KEY}",
            "Content-Type": "application/json",
        }
        body_dict: dict = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_images": 1,
            "guidance_scale": 7,
            "modelId": "b24e16ff-06e3-43eb-8d33-4416c2d75876",  # Leonardo Diffusion XL
        }
        if style_uuid:
            body_dict["styleUUID"] = style_uuid

        req = urllib.request.Request(
            f"{LEONARDO_URL}/generations",
            data=json.dumps(body_dict).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        gen_id = data.get("sdGenerationJob", {}).get("generationId")
        if not gen_id:
            log.warning(f"[MediaEngine] Leonardo: no generationId in response")
            return None

        # Poll for result
        for _ in range(20):
            time.sleep(4)
            req2 = urllib.request.Request(
                f"{LEONARDO_URL}/generations/{gen_id}",
                headers=headers,
            )
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                result = json.loads(resp2.read())
            imgs = result.get("generations_by_pk", {}).get("generated_images", [])
            if imgs:
                url = imgs[0].get("url")
                log.info(f"[MediaEngine] Leonardo → {url[:60] if url else 'None'}")
                return url
        log.warning("[MediaEngine] Leonardo: timed out polling")
        return None
    except Exception as e:
        log.warning(f"[MediaEngine] Leonardo error: {e}")
        return None


# ─── Video backends ──────────────────────────────────────────────────────────

def _runway_video(image_url: str, prompt: str, duration: int = 5) -> Optional[str]:
    """
    Generate a product video from an image using Runway Gen-3 Alpha Turbo.
    Polls until complete (max ~3 min). Returns video URL or None.
    """
    if not RUNWAY_KEY:
        return None
    try:
        import urllib.request
        headers = {
            "Authorization": f"Bearer {RUNWAY_KEY}",
            "Content-Type": "application/json",
            "X-Runway-Version": "2024-11-06",
        }
        body = json.dumps({
            "model": "gen3a_turbo",
            "promptImage": image_url,
            "promptText": prompt,
            "duration": duration,
            "ratio": "1280:720",
        }).encode()

        req = urllib.request.Request(
            f"{RUNWAY_URL}/image_to_video",
            data=body,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        task_id = data.get("id")
        if not task_id:
            log.warning(f"[MediaEngine] Runway: no task id — {data}")
            return None

        log.info(f"[MediaEngine] Runway task {task_id} started, polling…")
        for _ in range(36):  # max ~3 min
            time.sleep(5)
            req2 = urllib.request.Request(
                f"{RUNWAY_URL}/tasks/{task_id}",
                headers=headers,
            )
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                task = json.loads(resp2.read())
            status = task.get("status", "")
            if status == "SUCCEEDED":
                url = task.get("output", [None])[0]
                log.info(f"[MediaEngine] Runway video → {url[:60] if url else 'None'}")
                return url
            if status in ("FAILED", "CANCELLED"):
                log.warning(f"[MediaEngine] Runway task {status}: {task.get('failure')}")
                return None
        log.warning(f"[MediaEngine] Runway: timed out on task {task_id}")
        return None
    except Exception as e:
        log.warning(f"[MediaEngine] Runway error: {e}")
        return None


def _luma_video(prompt: str, image_url: str = None) -> Optional[str]:
    """
    Generate a video with Luma AI Dream Machine.
    Polls until complete (max ~4 min). Returns video URL or None.
    """
    if not LUMA_KEY:
        return None
    try:
        import urllib.request
        headers = {
            "Authorization": f"Bearer {LUMA_KEY}",
            "Content-Type": "application/json",
        }
        body_dict: dict = {
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "loop": False,
        }
        if image_url:
            body_dict["keyframes"] = {"frame0": {"type": "image", "url": image_url}}

        req = urllib.request.Request(
            f"{LUMA_URL}/generations",
            data=json.dumps(body_dict).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        gen_id = data.get("id")
        if not gen_id:
            log.warning(f"[MediaEngine] Luma: no generation id — {data}")
            return None

        log.info(f"[MediaEngine] Luma generation {gen_id} started, polling…")
        for _ in range(30):  # max ~4 min
            time.sleep(8)
            req2 = urllib.request.Request(
                f"{LUMA_URL}/generations/{gen_id}",
                headers=headers,
            )
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                gen = json.loads(resp2.read())
            state = gen.get("state", "")
            if state == "completed":
                url = gen.get("assets", {}).get("video")
                log.info(f"[MediaEngine] Luma video → {url[:60] if url else 'None'}")
                return url
            if state == "failed":
                log.warning(f"[MediaEngine] Luma failed: {gen.get('failure_reason')}")
                return None
        log.warning(f"[MediaEngine] Luma: timed out on generation {gen_id}")
        return None
    except Exception as e:
        log.warning(f"[MediaEngine] Luma error: {e}")
        return None


# ─── High-level generators ────────────────────────────────────────────────────

def generate_cover_images(product_data: dict, count: int = 3) -> list[str]:
    """
    Generate multiple cover images for a product.
    Returns list of publicly accessible image URLs.
    """
    title       = product_data.get("title", "Digital Product")
    ptype       = product_data.get("_product_type_key", "digital_product")
    tagline     = product_data.get("tagline", "")
    niche       = product_data.get("_niche", "")

    prompts = [
        # Style 1: premium dark gradient — main cover
        (
            f"Professional premium digital product cover for '{title}', "
            f"{ptype.replace('_',' ')} product, dark gradient background with purple-blue to teal, "
            "glowing neon accent lines, bold clean typography, high-end SaaS marketing visual, "
            "4K quality, ultra-sharp, commercial photography style"
        ),
        # Style 2: light minimal — lifestyle
        (
            f"Clean minimalist product mockup for '{title}', "
            f"white background with soft shadows, floating device screen with glowing UI, "
            f"{tagline or 'premium digital download'}, "
            "lifestyle photography, bright and modern, flat lay style, Apple product aesthetic"
        ),
        # Style 3: bold social-media-ready — thumbnail
        (
            f"Bold social media product thumbnail for '{title}', "
            f"{niche or ptype.replace('_',' ')} category, "
            "vibrant orange and gold gradient, big bold text placement area, "
            "YouTube thumbnail style, high contrast, eye-catching, viral-ready design, 8K render"
        ),
    ]

    urls: list[str] = []
    for i, prompt in enumerate(prompts[:count]):
        # First image: HD quality on DALL-E 3
        url = _dalle3(prompt, quality="hd" if i == 0 else "standard")
        if not url:
            url = _leonardo(prompt, style_uuid=_LEO_PROMO_STYLE)
        if url:
            urls.append(url)
            log.info(f"[MediaEngine] Cover {i+1}/{count} generated")
        time.sleep(1)

    return urls


def generate_3d_mockup(product_data: dict) -> Optional[str]:
    """
    Generate a photorealistic 3D product mockup image.
    Returns URL or None.
    """
    title = product_data.get("title", "Digital Product")
    ptype = product_data.get("_product_type_key", "digital")

    prompt = (
        f"Photorealistic 3D product mockup for '{title}', "
        f"category: {ptype.replace('_', ' ')}, "
        "3D floating device with glowing product UI on screen, "
        "dark studio background with volumetric soft lighting, "
        "premium tech product photography, cinematic depth of field, "
        "octane render, 8K, hyper-realistic material shaders, "
        "subtle blue-purple rim light, product launch quality"
    )

    # Leonardo has better 3D capabilities
    url = _leonardo(prompt, style_uuid=_LEO_3D_STYLE)
    if not url:
        url = _dalle3(prompt, quality="hd")
    return url


def generate_product_video(product_data: dict, cover_image_url: str = None) -> Optional[str]:
    """
    Generate a short (5 s) product showcase animation/video.
    Returns a video URL suitable for Shopify media upload, or None.
    """
    title   = product_data.get("title", "Digital Product")
    tagline = product_data.get("tagline", "")

    motion_prompt = (
        f"Smooth cinematic product showcase for '{title}', "
        f"{tagline}, "
        "slow dramatic zoom in toward glowing product screen, "
        "particles and light orbs floating in background, "
        "premium brand commercial feel, 5 seconds, dark luxury atmosphere, "
        "epic motion graphics, professional product reveal animation"
    )

    video_url: Optional[str] = None

    # Runway Gen-3 (image-to-video) is highest quality
    if cover_image_url and RUNWAY_KEY:
        log.info("[MediaEngine] Trying Runway ML Gen-3 for video…")
        video_url = _runway_video(cover_image_url, motion_prompt, duration=5)

    # Luma AI as fallback
    if not video_url and LUMA_KEY:
        log.info("[MediaEngine] Trying Luma AI Dream Machine for video…")
        video_url = _luma_video(motion_prompt, cover_image_url)

    return video_url


def generate_full_media_pack(product_data: dict) -> dict:
    """
    Generate the complete media pack for a product:
      • 3 cover images (dark premium / minimal lifestyle / bold social)
      • 1 × 3D product mockup
      • 1 × video animation (5 s showcase)

    Returns:
    {
      covers: [url, ...],
      mockup_3d: url | None,
      video: url | None,
      all_media: [{type, url}, ...],
      errors: [...],
    }
    """
    title = product_data.get("title", "?")
    log.info(f"[MediaEngine] Generating full media pack for: {title}")

    result: dict = {
        "covers":    [],
        "mockup_3d": None,
        "video":     None,
        "all_media": [],
        "errors":    [],
    }

    # 1. Cover images (3 variations)
    try:
        covers = generate_cover_images(product_data, count=3)
        result["covers"] = covers
        result["all_media"].extend({"type": "image", "url": u} for u in covers)
    except Exception as e:
        result["errors"].append(f"covers: {e}")
        log.warning(f"[MediaEngine] Cover generation error: {e}")

    # 2. 3D mockup
    try:
        mockup = generate_3d_mockup(product_data)
        if mockup:
            result["mockup_3d"] = mockup
            result["all_media"].append({"type": "image", "url": mockup})
    except Exception as e:
        result["errors"].append(f"3d_mockup: {e}")
        log.warning(f"[MediaEngine] 3D mockup error: {e}")

    # 3. Product video (source: first cover image for best continuity)
    try:
        source_img = result["covers"][0] if result["covers"] else None
        video = generate_product_video(product_data, source_img)
        if video:
            result["video"] = video
            result["all_media"].append({"type": "video", "url": video})
    except Exception as e:
        result["errors"].append(f"video: {e}")
        log.warning(f"[MediaEngine] Video generation error: {e}")

    n_img = len([m for m in result["all_media"] if m["type"] == "image"])
    n_vid = len([m for m in result["all_media"] if m["type"] == "video"])
    log.info(
        f"[MediaEngine] Pack ready for '{title}': "
        f"{n_img} images, {n_vid} videos, {len(result['errors'])} errors"
    )
    return result


def upload_media_pack_to_shopify(product_id: int, media_pack: dict) -> dict:
    """
    Upload the full media pack to a Shopify product.
    Images  → POST /products/{id}/images.json
    Videos  → POST /products/{id}/media.json

    Returns: {images: [...ids], videos: [...ids], errors: [...]}
    """
    from core.shopify_client import _shopify_request   # type: ignore

    uploaded: dict = {"images": [], "videos": [], "errors": []}

    for item in media_pack.get("all_media", []):
        url       = item.get("url", "")
        mtype     = item.get("type", "image")
        if not url:
            continue

        try:
            if mtype == "image":
                r = _shopify_request("POST", f"products/{product_id}/images.json", {
                    "image": {"src": url, "alt": f"Product image"}
                })
                img_id = r.get("image", {}).get("id")
                if img_id:
                    uploaded["images"].append(img_id)
                    log.info(f"[MediaEngine] Image {img_id} uploaded to product {product_id}")
                else:
                    uploaded["errors"].append(f"image upload: no id — {r}")

            elif mtype == "video":
                # Shopify Product Media API (REST 2021-01+)
                r = _shopify_request("POST", f"products/{product_id}/media.json", {
                    "media": {
                        "original_source": url,
                        "media_content_type": "VIDEO",
                        "alt": "Product showcase video",
                    }
                })
                media_id = r.get("media", {}).get("id")
                if media_id:
                    uploaded["videos"].append(media_id)
                    log.info(f"[MediaEngine] Video {media_id} uploaded to product {product_id}")
                else:
                    uploaded["errors"].append(f"video upload: no id — {r}")

        except Exception as e:
            uploaded["errors"].append(f"{mtype}: {e}")
            log.warning(f"[MediaEngine] Upload error ({mtype}): {e}")

    return uploaded


def generate_and_upload(product_id: int, product_data: dict) -> dict:
    """
    Convenience: generate full media pack and upload to Shopify in one call.
    Returns combined result dict.
    """
    pack   = generate_full_media_pack(product_data)
    upload = upload_media_pack_to_shopify(product_id, pack)
    return {
        "product_id":  product_id,
        "covers":      len(pack["covers"]),
        "has_3d":      pack["mockup_3d"] is not None,
        "has_video":   pack["video"] is not None,
        "uploaded_images": len(upload["images"]),
        "uploaded_videos": len(upload["videos"]),
        "media_errors":    pack["errors"] + upload["errors"],
    }
