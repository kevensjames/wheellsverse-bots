"""Local image generation via diffusers — drop-in for OpenAI images.generate.

Returns a SimpleNamespace that mimics the OpenAI Images.generate response:
    resp.data[0].url        → file://<absolute path to PNG> (local file)
    resp.data[0].b64_json   → base64-encoded PNG bytes
    resp.data[0].revised_prompt → echo of the input prompt

That way the same caller code that did `client.images.generate(...).data[0].url`
or `.b64_json` works unchanged, just routed through this module.

Default model: stabilityai/sdxl-turbo (~7 GB on first run, single-step inference).
Override via LOCAL_IMAGE_MODEL env. Sizes other than 512x512 are generated at the
model's native resolution then upscaled with PIL bilinear — fine for previews
and IG posts; for KDP book covers you may want a higher-quality upscaler.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

logger = logging.getLogger("local_image")

_PIPELINE_CACHE: dict[str, object] = {}
_DEFAULT_MODEL = "stabilityai/sdxl-turbo"
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "local_images"


def _parse_size(size: str) -> tuple[int, int]:
    """'1024x1536' → (1024, 1536). Fall back to 1024x1024 if unparseable."""
    try:
        w_str, h_str = size.lower().split("x", 1)
        return max(64, int(w_str)), max(64, int(h_str))
    except Exception:
        return 1024, 1024


def _get_pipeline(model_id: Optional[str] = None):
    """Lazy-load + cache the diffusion pipeline."""
    model = model_id or os.getenv("LOCAL_IMAGE_MODEL", _DEFAULT_MODEL)
    if model in _PIPELINE_CACHE:
        return _PIPELINE_CACHE[model]

    import torch
    from diffusers import AutoPipelineForText2Image

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32

    logger.info(f"Loading {model} on {device} (first call downloads ~7 GB)")
    pipe = AutoPipelineForText2Image.from_pretrained(
        model, torch_dtype=dtype, variant="fp16" if device == "mps" else None,
    )
    pipe = pipe.to(device)
    # SDXL-Turbo / SD-Turbo guidance scale must be 0.0 for single-step.
    _PIPELINE_CACHE[model] = pipe
    return pipe


def _is_turbo(model_id: str) -> bool:
    return "turbo" in model_id.lower() or "lightning" in model_id.lower() or "lcm" in model_id.lower()


def generate(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "standard",
    n: int = 1,
    response_format: str = "url",
    model: Optional[str] = None,
) -> object:
    """Generate one or more PNGs locally; return an OpenAI-shape response shim.

    Args:
        prompt: text prompt
        size: e.g. '1024x1024', '1024x1536', '512x512'
        quality: 'standard' or 'hd' (controls inference steps for non-turbo models)
        n: number of images
        response_format: 'url' or 'b64_json' (both fields are always populated)
        model: HF model id; defaults to env LOCAL_IMAGE_MODEL or SDXL-Turbo

    Returns:
        SimpleNamespace with .data list, each entry has .url, .b64_json, .revised_prompt.
    """
    target_w, target_h = _parse_size(size)
    model_id = model or os.getenv("LOCAL_IMAGE_MODEL", _DEFAULT_MODEL)
    pipe = _get_pipeline(model_id)

    # Inference settings: turbo models run 1 step at guidance 0; full SDXL needs 20-30.
    if _is_turbo(model_id):
        steps = 1 if quality == "standard" else 4
        guidance = 0.0
    else:
        steps = 20 if quality == "standard" else 30
        guidance = 7.5

    # Native generation size: 512 for SDXL-Turbo, 1024 for SDXL base.
    native = 512 if _is_turbo(model_id) else 1024

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data_entries = []
    for _ in range(n):
        result = pipe(
            prompt=prompt[:4000],
            num_inference_steps=steps,
            guidance_scale=guidance,
            height=native,
            width=native,
        )
        img = result.images[0]
        if (target_w, target_h) != (native, native):
            from PIL import Image
            img = img.resize((target_w, target_h), Image.LANCZOS)

        # Save and encode
        with tempfile.NamedTemporaryFile(
            suffix=".png", prefix="local_img_", dir=_OUTPUT_DIR, delete=False
        ) as f:
            img.save(f, format="PNG")
            path = Path(f.name)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        data_entries.append(SimpleNamespace(
            url=f"file://{path.resolve()}",
            b64_json=b64,
            revised_prompt=prompt[:4000],
        ))

    return SimpleNamespace(
        created=int(__import__("time").time()),
        data=data_entries,
    )


def is_available() -> bool:
    """Cheap check: dependencies present (does NOT trigger model download)."""
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def should_use_local() -> bool:
    """Are we configured to route images locally?"""
    explicit = (os.getenv("IMAGE_PROVIDER") or "").strip().lower()
    if explicit in ("local", "diffusers", "sdxl"):
        return True
    if explicit in ("openai", "dalle"):
        return False
    # Piggyback on LLM_BACKEND for consistency with text/audio.
    return (os.getenv("LLM_BACKEND") or "").strip().lower() in ("ollama", "local", "lmstudio", "llamacpp")
