"""site_builder — KAI generates a self-contained HTML page/section in the
WheellsVerse house style, saved as a reviewable DRAFT (never auto-published).

The in-daemon counterpart to building sites with Claude Code: KAI takes a brief
and produces a single self-contained HTML file (inline CSS, the obsidian
command-deck aesthetic), writes it to a drafts dir, and returns the path +
preview. The operator reviews and publishes — KAI never deploys on its own.

Uses KAI's own router (prefer_local so it runs free on Ollama). Fail-soft.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)

_DRAFTS = Path(os.environ.get("KAI_SITE_DRAFTS_DIR", "data/site_drafts"))
_SLUG_RE = re.compile(r"[^a-z0-9_]+")

# The WheellsVerse design system, embedded so generated pages match the site
# (see frontend/index.html). Kept terse but specific.
_STYLE = (
    "WheellsVerse house style (match it exactly): DARK premium 'obsidian command "
    "deck'. Base #07080c, panels rgba(255,255,255,.04) with 1px rgba(255,255,255,.08) "
    "borders + border-radius 18px. Accent gradient linear-gradient(115deg,#0ea5e9,"
    "#a855f7,#d946ef); gold #f5c451 for highlights; text #eef1f8, dim #aeb6c9. "
    "Fonts via CDN: display 'Clash Display' + body 'Satoshi' (api.fontshare.com), "
    "mono 'JetBrains Mono' (Google Fonts). Use a subtle aurora radial-gradient "
    "backdrop + faint grain, generous spacing, gradient-text headings, glassmorphic "
    "cards, and scroll-reveal that is progressively enhanced (hidden only under "
    "html.js so it degrades visible without JS). KAI is the autonomous-operator brand."
)

_SYSTEM = (
    "You are KAI's site builder. Produce ONE self-contained HTML document (inline "
    "<style>, minimal vanilla JS, no external build) for the WheellsVerse site. "
    "Return ONLY the HTML — no markdown fences, no commentary. It must be valid, "
    "responsive, accessible, and visually polished.\n\n" + _STYLE
)


def _slug(brief: str) -> str:
    s = _SLUG_RE.sub("_", brief.strip().lower()).strip("_")
    return (s or "page")[:50]


class SiteBuilderTool:
    name = "site_builder"
    description = (
        "Generate a self-contained HTML page or section in the WheellsVerse house "
        "style (dark premium, KAI brand) from a brief. Saves it as a reviewable "
        "DRAFT file and returns the path + a preview — it does NOT publish or "
        "deploy. Use when asked to build/draft a landing page, section, or site."
    )
    parameters = {
        "type": "object",
        "properties": {
            "brief": {
                "type": "string",
                "description": "What to build, e.g. 'a pricing section with 3 tiers' "
                               "or 'a landing page for the KDP books catalog'.",
            },
            "kind": {
                "type": "string",
                "enum": ["page", "section"],
                "description": "Full HTML page or an embeddable section. Default page.",
            },
        },
        "required": ["brief"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        brief = (kwargs.get("brief") or "").strip()
        if not brief:
            raise ToolError("brief is required")
        kind = (kwargs.get("kind") or "page").strip().lower()
        if kind not in ("page", "section"):
            kind = "page"

        try:
            from app.services.router import build_default_router
            router = build_default_router(ctx.session)
        except Exception as e:
            raise ToolError(f"router unavailable: {e}")

        user_msg = (
            f"Build a {kind} for the WheellsVerse site. Brief: {brief}\n"
            + ("Return a COMPLETE standalone HTML document." if kind == "page"
               else "Return an embeddable HTML section (a <section>…</section> plus "
                    "a scoped <style>), not a full document.")
        )
        try:
            result = router.complete(
                user_id=ctx.user_id,
                messages=[{"role": "user", "content": user_msg}],
                system=_SYSTEM,
                max_tokens=4096,
                temperature=0.4,
                prefer_local=True,  # free + private; falls back to cloud if local is down
            )
        except Exception as e:
            raise ToolError(f"generation failed: {e}")

        html = (result.content or "").strip()
        # Strip stray markdown fences if the model added them.
        if html.startswith("```"):
            html = re.sub(r"^```[a-zA-Z]*\n?", "", html)
            html = re.sub(r"\n?```$", "", html).strip()
        if not html or "<" not in html:
            return {"brief": brief, "kind": kind, "html_preview": "",
                    "note": "KAI did not return usable HTML — try a more specific brief.",
                    "raw": (result.content or "")[:600]}

        slug = _slug(brief)
        _DRAFTS.mkdir(parents=True, exist_ok=True)
        path = _DRAFTS / f"{slug}.html"
        path.write_text(html)
        return {
            "brief": brief, "kind": kind,
            "draft_path": str(path),
            "bytes": len(html),
            "html_preview": html[:600],
            "note": (
                "DRAFT saved — KAI generated this in the WheellsVerse style but did "
                "NOT publish it. Review the file, then deploy via the static host."
            ),
        }
