"""adapter_codegen — KAI drafts its OWN native adapter/tool for a capability,
as a REVIEWABLE artifact for the operator to approve.

This is the safe-autonomy answer to "discover + integrate by itself": instead of
fetching and running third-party code (hard-blocked, and unsafe), KAI writes a
*native* KAI tool implementing the capability, following KAI's own conventions,
and saves it as a DRAFT artifact. The operator reads the actual code, and — if
they want it live — applies it through the normal git review/commit loop.

Safety boundary (load-bearing): this module ONLY generates text and writes it to
a drafts directory that is NOT on the import path. It NEVER imports, executes,
applies, or registers the generated code, and never touches the live app/ tree
or restarts anything. So "what the operator approves" is readable code KAI
wrote — not an unaudited repo + its dependency tree.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DRAFTS = Path(os.environ.get("KAI_INTEGRATION_DRAFTS_DIR", "data/integration_drafts"))
_SLUG_RE = re.compile(r"[^a-z0-9_]+")

# Concise spec of KAI's tool-extension point, embedded in the prompt so the
# generated adapter actually fits the codebase (duck-typed Tool protocol +
# how it gets registered). Mirrors app/services/tools/base.py + github_scout.
_CONVENTIONS = '''\
KAI tools are duck-typed (app/services/tools/base.py):

    class MyTool:
        name = "snake_case_name"
        description = "One clear sentence the LLM reads to decide when to call it."
        parameters = {  # JSON Schema for the args
            "type": "object",
            "properties": {"query": {"type": "string", "description": "..."}},
            "required": ["query"],
        }
        def execute(self, ctx: ToolContext, **kwargs) -> dict:
            # ctx has .user_id (uuid) and .session (SQLAlchemy Session).
            # Raise ToolError("...") for user-facing failures. Return a
            # JSON-serializable dict. Prefer stdlib (urllib) for HTTP; be
            # fail-soft; never read secrets or run shell commands.
            ...

Imports available: `from app.services.tools.base import ToolContext, ToolError`.
It is registered by adding `reg.register(MyTool())` in
app/services/tools/__init__.py build_default_registry(), and (optionally)
whitelisted in a preset in app/services/presets/registry.py.
Style: stdlib-first, type hints, a module docstring, no external pip deps unless
already in the project, read-only / no side effects where possible.
'''

_SYSTEM = (
    "You are KAI writing a NEW native tool to extend your own capabilities. "
    "Produce a single, self-contained Python module implementing one tool that "
    "fits KAI's conventions exactly. The code will be REVIEWED by the operator "
    "before it is ever run — make it correct, minimal, and safe (no secrets, no "
    "shell-outs, no arbitrary code execution, fail-soft). Use the reference repo "
    "only as a DESIGN reference; do NOT import or depend on it.\n\n"
    + _CONVENTIONS +
    "\nReturn ONLY a JSON object with keys: filename (e.g. "
    "\"app/services/tools/<name>.py\"), tool_class_name, code (the full module "
    "as a string), rationale (1-2 sentences), how_to_register (the exact lines "
    "to add to build_default_registry + any preset), risks (string)."
)


def _slug(capability: str) -> str:
    s = _SLUG_RE.sub("_", capability.strip().lower()).strip("_")
    return (s or "capability")[:50]


def _parse_json(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction — strips ```json fences, else grabs the first
    balanced {...}. Returns None if nothing parses."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        return None
    return None


def draft_adapter(
    capability: str,
    *,
    router,
    user_id,
    reference_repo: str | None = None,
    reference_url: str | None = None,
    prefer_local: bool = False,
) -> dict[str, Any]:
    """Generate a native KAI tool for `capability` as a reviewable DRAFT.

    Returns {capability, filename, tool_class_name, code, parses (bool),
    rationale, how_to_register, risks, draft_path, cost_usd, note}. The code is
    written to a drafts dir (never the import path) — NOT applied or executed.
    """
    capability = (capability or "").strip()
    if not capability:
        raise ValueError("capability is required")

    ref = ""
    if reference_repo:
        ref = f"\nReference design (do NOT import it): {reference_repo}"
        if reference_url:
            ref += f" ({reference_url})"
    user_msg = (
        f"Capability to implement as a native KAI tool: {capability}.{ref}\n"
        "Design the smallest tool that delivers real value for this capability "
        "and return the JSON object."
    )

    result = router.complete(
        user_id=user_id,
        messages=[{"role": "user", "content": user_msg}],
        system=_SYSTEM,
        max_tokens=2200,
        temperature=0.2,
        prefer_local=prefer_local,
    )
    cost = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
    parsed = _parse_json(result.content or "")
    if not parsed or not parsed.get("code"):
        return {
            "capability": capability, "code": "", "parses": False,
            "cost_usd": cost,
            "note": "KAI did not return usable code — try again or rephrase.",
            "raw": (result.content or "")[:1200],
        }

    code = str(parsed.get("code", ""))
    try:
        ast.parse(code)
        parses = True
    except SyntaxError as e:
        parses = False
        logger.warning("adapter_codegen: draft for %r has a syntax error: %s", capability, e)

    slug = _slug(capability)
    draft_dir = _DRAFTS / slug
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "adapter.py").write_text(code)
    meta = {
        "capability": capability,
        "filename": parsed.get("filename"),
        "tool_class_name": parsed.get("tool_class_name"),
        "rationale": parsed.get("rationale"),
        "how_to_register": parsed.get("how_to_register"),
        "risks": parsed.get("risks"),
        "reference_repo": reference_repo,
        "parses": parses,
    }
    (draft_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    return {
        "capability": capability,
        "filename": parsed.get("filename"),
        "tool_class_name": parsed.get("tool_class_name"),
        "code": code,
        "parses": parses,
        "rationale": parsed.get("rationale"),
        "how_to_register": parsed.get("how_to_register"),
        "risks": parsed.get("risks"),
        "draft_path": str(draft_dir / "adapter.py"),
        "cost_usd": cost,
        "note": (
            "DRAFT ONLY — KAI wrote this; it is NOT applied, imported, or run. "
            "Review the code, then apply it through normal git review/commit if "
            "you want it live." + ("" if parses else
            " ⚠️ This draft has a syntax error — review carefully or regenerate.")
        ),
    }


def list_drafts() -> list[dict[str, Any]]:
    """Drafts on disk (metadata only)."""
    out: list[dict[str, Any]] = []
    if not _DRAFTS.exists():
        return out
    for d in sorted(_DRAFTS.iterdir()):
        mf = d / "meta.json"
        if mf.exists():
            try:
                out.append(json.loads(mf.read_text()))
            except Exception:
                continue
    return out
