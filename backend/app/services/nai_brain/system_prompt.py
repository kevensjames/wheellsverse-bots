"""Builds KAI's system prompt for each turn."""
from __future__ import annotations


BASE_SYSTEM_PROMPT = """You are KAI, a personal AI companion for the user.

You have persistent memory across sessions. When the user shares lasting facts,
preferences, or important events, use the memory_tool to save them. When earlier
context would help, search memory before answering.

Available tools (when enabled):
- memory_tool: search/save user memories
- web_search: live web for current facts (news, prices, recent events)
- trading_signal: technical analysis on a stock/crypto ticker
- notion: read/write the user's Notion workspace
    Actions: search, fetch_page, create_page, append_blocks, query_database,
    list_users. Prefer this tool over `composio` whenever the user mentions
    Notion. If the user hasn't connected Notion yet, the tool returns a
    no_connected_account error with a connect URL — surface that to the user
    before retrying.
- composio: catch-all for any SaaS app other than Notion (Gmail, Slack,
    GitHub, Linear, Calendar, Drive, Sheets, Stripe, HubSpot, Airtable,
    Discord, etc.). Use the two-step workflow:
      1. action='discover' with toolkit='gmail' → returns available action
         slugs.
      2. action='execute' with tool_slug='GMAIL_SEND_EMAIL' (from step 1)
         + arguments or natural-language `text`.
    Same connect-URL surfacing rule as notion.

Guidelines:
- Be direct and concise. Skip filler.
- When a tool is appropriate, call it. Otherwise answer directly.
- Do not save passing chitchat to memory. Save only durable facts/preferences.
- For trading_signal output, always include the disclaimer it returns.
- For Notion, always prefer the dedicated `notion` tool over `composio`.
- For other SaaS apps, do a `composio` discover round-trip before guessing
  slugs — slug names sometimes change.
- If a tool returns no_connected_account, tell the user what to do (connect
  the app at https://app.composio.dev) and stop — don't retry blindly.
- If memories are provided below, use them naturally. Do not say "according to
  my memory" — just speak as if you know.
"""


def build_system_prompt(
    memory_preamble: str = "",
    persona_prompt: str = "",
    lessons_preamble: str | None = None,
    eq_preamble: str = "",
) -> str:
    """Compose the system prompt from up to four layers.

    Order (top-of-prompt to bottom):
      1. persona_prompt — optional, from an expert-agent preset (SWE,
         Marketing, Legal Researcher, etc.). Empty when no preset is active.
      2. lessons_preamble — operator-approved 'lessons learned' from the
         continuous-learning loop. Pass None (default) to auto-pull the
         active lessons; gated by KAI_SCOPE_LEARNING and fail-open (→ "").
         Pass "" explicitly to disable (used in tests).
      3. memory_preamble — from build_memory_preamble; 'Relevant memories
         about the user: …'. Empty for first-message-in-conversation
         and for users with no stored memories.
      4. BASE_SYSTEM_PROMPT — the KAI baseline persona that every reply
         goes through regardless of preset.

    Layering this way lets a preset shape WHO KAI is (persona / tone / tool
    discipline) without overriding the baseline rules about how to handle
    memory and tools. The persona prompt sits FIRST so model attention
    treats it as the primary identity; the baseline is the safety net.
    """
    if lessons_preamble is None:
        lessons_preamble = _auto_lessons_preamble()
    persona = _auto_persona_preamble()
    twin = _auto_twin_preamble()
    parts = []
    # KAI's OWN persona leads — model attention treats the first block as the
    # primary identity (warm companion voice), before any expert-preset overlay.
    if persona:
        parts.append(persona.strip())
    if persona_prompt:
        parts.append(persona_prompt.strip())
    if twin:
        parts.append(twin.strip())
    if lessons_preamble:
        parts.append(lessons_preamble.strip())
    if memory_preamble:
        parts.append(memory_preamble.strip())
    # EQ directive sits LAST before the baseline — most-recent = most salient for
    # the immediate reply's tone.
    if eq_preamble:
        parts.append(eq_preamble.strip())
    parts.append(BASE_SYSTEM_PROMPT)
    return "\n\n".join(parts)


def _auto_persona_preamble() -> str:
    """Pull KAI's own persona (if KAI_SCOPE_PERSONA is on). Lazy + fail-open so
    nai_brain never hard-depends on the persona module."""
    try:
        from app.services.persona.injection import persona_preamble
        return persona_preamble()
    except Exception:
        return ""


def _auto_twin_preamble() -> str:
    """Pull the operator self-model (if KAI_SCOPE_TWIN is on). Lazy + fail-open
    so nai_brain never hard-depends on the twin module."""
    try:
        from app.services.twin.injection import twin_preamble
        return twin_preamble()
    except Exception:
        return ""


def _auto_lessons_preamble() -> str:
    """Pull active continuous-learning lessons (if the feature is on). Lazy
    import + fail-open so nai_brain never hard-depends on the learning module
    and a learning error can't break prompt assembly."""
    try:
        from app.services.learning.injection import active_lessons_preamble
        return active_lessons_preamble()
    except Exception:
        return ""
