"""
core/narai_self_improve.py
─────────────────────────────────────────────────────────────────────────────
NarAI Self-Improvement Engine.

Analyses recent conversation history and produces concrete proposals to
improve NarAI's system prompt or tool capabilities. Proposals are stored
in data/narai_proposals.json and can be approved / rejected from the
dashboard.  Approved proposals are appended to
data/narai_prompt_overrides.txt, which is injected into the system prompt
at chat time by narai_chat.py.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("narai.self_improve")

_PROPOSALS_PATH = Path("data/narai_proposals.json")
_OVERRIDES_PATH = Path("data/narai_prompt_overrides.txt")

# ─── Storage helpers ──────────────────────────────────────────────────────────

def _load_proposals() -> list[dict]:
    if _PROPOSALS_PATH.exists():
        try:
            return json.loads(_PROPOSALS_PATH.read_text())
        except Exception:
            pass
    return []


def _save_proposals(proposals: list[dict]) -> None:
    _PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))


# ─── Prompt override loading (used by narai_chat.py) ─────────────────────────

def load_prompt_overrides() -> str:
    """Return any approved prompt additions, or empty string."""
    if _OVERRIDES_PATH.exists():
        try:
            return _OVERRIDES_PATH.read_text().strip()
        except Exception:
            pass
    return ""


# ─── Analysis prompt ─────────────────────────────────────────────────────────

_ANALYST_SYSTEM = """You are an AI meta-analyst reviewing conversation logs for NarAI.
Your job: identify ONE concrete, actionable improvement for NarAI's behaviour.
Focus on patterns of failure, missed opportunities, or user frustration.
Respond in strict JSON only:
{
  "proposal": "<one sentence describing the specific change>",
  "rationale": "<two sentences explaining why — cite evidence from the logs>",
  "type": "system_prompt" | "capability" | "tone"
}
Do NOT include markdown fences. Output raw JSON only."""


# ─── Core analysis function ───────────────────────────────────────────────────

def generate_improvement_proposal(user_id: Optional[str] = None) -> dict:
    """
    Analyse recent conversation history and produce one improvement proposal.
    Saves the proposal to data/narai_proposals.json.
    Returns the proposal dict.
    """
    # 1. Gather recent messages
    messages_sample: list[str] = []
    try:
        from core.narai_user import list_conversations, get_conversation_messages
        convos = list_conversations(user_id or "global", limit=10) if user_id else []
        for c in convos[:5]:
            msgs = get_conversation_messages(c["id"], user_id, limit=10)
            for m in msgs:
                role = m.get("role", "?")
                content = str(m.get("content", ""))[:300]
                messages_sample.append(f"[{role}]: {content}")
    except Exception as e:
        log.warning("Could not load conversation history: %s", e)

    if not messages_sample:
        messages_sample = ["[system]: No conversation history available yet. "
                           "Propose a general improvement to NarAI's onboarding experience."]

    log_text = "\n".join(messages_sample[:50])

    # 2. Ask AI to analyse
    proposal_data: dict = {}
    try:
        proposal_data = _ask_ai(log_text)
    except Exception as e:
        log.error("AI analysis failed: %s", e)
        proposal_data = {
            "proposal": "Improve NarAI's error recovery by providing more specific "
                        "guidance when API keys are missing or credits are exhausted.",
            "rationale": "Users frequently encounter silent failures. Clear actionable "
                         "messages reduce frustration and support requests.",
            "type": "system_prompt",
        }

    # 3. Build proposal record
    proposal = {
        "id": str(uuid.uuid4()),
        "proposal": proposal_data.get("proposal", ""),
        "rationale": proposal_data.get("rationale", ""),
        "type": proposal_data.get("type", "system_prompt"),
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }

    # 4. Save
    proposals = _load_proposals()
    proposals.insert(0, proposal)
    # Keep at most 50 proposals
    _save_proposals(proposals[:50])

    log.info("Proposal generated: %s", proposal["proposal"][:80])
    return proposal


def _ask_ai(log_text: str) -> dict:
    """Call Claude or OpenAI to analyse conversation logs."""
    user_content = (
        "Here are recent NarAI conversation snippets:\n\n"
        f"{log_text}\n\n"
        "Produce ONE improvement proposal as JSON."
    )

    # Try Claude first
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key and not anthropic_key.startswith("sk-placeholder"):
        try:
            from core.claude_logged import create as claude_create
            resp = claude_create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=_ANALYST_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
                api_key=anthropic_key,
                bot_name="narai_self_improve",
            )
            raw = resp.content[0].text.strip()
            return json.loads(raw)
        except Exception as e:
            log.warning("Claude analysis failed, trying OpenAI: %s", e)

    # Try OpenAI (or Ollama via wrapper). When LLM_BACKEND=ollama the wrapper
    # routes to the local server even without an OPENAI_API_KEY set.
    openai_key = os.getenv("OPENAI_API_KEY", "")
    local_backend = (os.getenv("LLM_BACKEND") or "").strip().lower() in ("ollama", "local", "lmstudio", "llamacpp")
    if local_backend or (openai_key and not openai_key.startswith("sk-placeholder")):
        from core.llm_client import safe_openai_call
        resp = safe_openai_call(
            messages=[
                {"role": "system", "content": _ANALYST_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            model="gpt-4o-mini",
            max_tokens=400,
            bot_name="narai_self_improve",
        )
        raw = (resp.choices[0].message.content or "").strip()
        return json.loads(raw)

    raise RuntimeError("No AI provider available")


# ─── Apply / Reject ───────────────────────────────────────────────────────────

def apply_proposal(proposal_id: str) -> bool:
    """
    Mark proposal as applied and append it to the prompt overrides file.
    Returns True on success.
    """
    proposals = _load_proposals()
    for p in proposals:
        if p["id"] == proposal_id:
            if p["status"] != "pending":
                return False
            # Append to overrides
            _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
            override_text = f"\n\n## Applied Improvement ({p['created_at'][:10]})\n{p['proposal']}"
            with _OVERRIDES_PATH.open("a") as f:
                f.write(override_text)
            p["status"] = "applied"
            p["applied_at"] = datetime.now(timezone.utc).isoformat()
            _save_proposals(proposals)
            log.info("Proposal applied: %s", proposal_id)
            return True
    return False


def reject_proposal(proposal_id: str) -> bool:
    """Mark proposal as rejected."""
    proposals = _load_proposals()
    for p in proposals:
        if p["id"] == proposal_id:
            p["status"] = "rejected"
            _save_proposals(proposals)
            return True
    return False


def list_proposals(status: Optional[str] = None) -> list[dict]:
    """Return proposals, optionally filtered by status."""
    proposals = _load_proposals()
    if status:
        proposals = [p for p in proposals if p.get("status") == status]
    return proposals
