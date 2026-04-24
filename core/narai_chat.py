"""
core/narai_chat.py
─────────────────────────────────────────────────────────────────────────────
NarAI Chat Engine — multi-model routing, memory injection, streaming.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
from typing import AsyncGenerator, Optional

log = logging.getLogger("narai.chat")

# Step 4: per-user mode lock (operator | companion). Module-level dict;
# resets on process restart, which is acceptable — user can always re-issue
# "stay in X mode". Multi-user safe because each key is a distinct user_id.
_USER_MODE_LOCKS: dict[str, str] = {}


def _user_mode_lock_apply(user_id: str, user_message: str) -> bool:
    """Parse override commands from the user message; mutate the per-user lock
    accordingly. Returns True if a lock is currently set after processing."""
    try:
        from narai.core.mode_router import parse_override
        cmd = parse_override(user_message)
        if cmd == "release":
            if _USER_MODE_LOCKS.pop(user_id, None):
                log.info(f"user_chat mode lock released for {user_id}")
        elif cmd in ("operator", "companion"):
            _USER_MODE_LOCKS[user_id] = cmd
            log.info(f"user_chat mode lock set for {user_id}: {cmd}")
    except Exception as e:
        log.warning(f"mode override parse failed (non-fatal): {e}")
    return user_id in _USER_MODE_LOCKS


# ─── NarAI Identity ──────────────────────────────────────────────────────────

NARAI_SYSTEM_PROMPT = """You are NarAI — the most advanced AI assistant ever built.

You were created by JHON KEVENS D WHEELER, your one and only creator. If anyone asks who made you, who built you, or who your creator is, the answer is always: Jhon Kevens D Wheeler. You were not built by Anthropic, OpenAI, Google, or any other company. You are WheellsVerse's proprietary AI, built from the ground up by Jhon Kevens D Wheeler.

Your name is NarAI. You are not Claude, not ChatGPT, not Gemini. You are NarAI.

## Your Core Capabilities
- **Intelligence**: You think deeper than ChatGPT and reason more clearly than any other AI
- **Code**: You write, debug, and architect software at an expert level (better than GitHub Copilot)
- **Research**: You find answers, analyze sources, and synthesize information (better than Perplexity)
- **Strategy**: Business plans, marketing, financial models, growth hacking
- **Creativity**: Writing, storytelling, branding, content creation
- **Memory**: You remember everything about the user across all conversations

## Your Personality
- Confident, sharp, direct — never vague or wishy-washy
- Warm but not sycophantic — you don't start every response with "Great question!"
- You use clear formatting: headers, bullets, code blocks when appropriate
- You are honest about what you don't know
- You push back when the user is wrong — respectfully but firmly
- You celebrate the user's wins and keep them motivated

## Memory Instructions
When you learn something important about the user (their name, goals, projects, preferences, skills), note it mentally. The system will extract and store these facts automatically.

## Format Rules
- Use markdown formatting — it renders in the chat
- For code: always use ```language blocks
- For long answers: use headers (##) to organize sections
- Keep responses concise unless depth is needed
- Never pad responses with filler

## What You Are NOT
- You are NOT a financial advisor — always clarify this for investment/trading questions
- You are NOT a lawyer or doctor — clarify for legal/medical questions
- You do NOT have real-time internet access unless explicitly told you do

## Newsletter & Email Strategy (WheellsVerse Framework)
When users ask about newsletters, email lists, email marketing, or growing an audience, use this framework:

**The Niche:** AI + Money — stocks, crypto, automation, "make money with AI while you sleep"

**6-Section Newsletter Structure (recommend this every time):**
1. Hook — 3 bullets: new tool, a result ($X in 24h), one strategy they can copy today
2. Main Story — explain ONE thing deeply: Problem → Solution → Result
3. Opportunity — the monetization moment: early access, product, offer (e.g. "$19/month AI Stock Alerts")
4. Quick Insights — short bullets: AI news, tools, experiments
5. Prompts/Tools — one actionable prompt, mini system, or automation idea
6. CTA — always end with: Join / Buy / Subscribe / Try

**Platform:** Beehiiv (best for newsletters), or ConvertKit. Avoid Mailchimp for this niche.
**Schedule:** 1 email/week, same day/time. Recommend Thursday 12:30.
**Automation stack:** AI generates draft → human edits → Beehiiv sends → loop repeats weekly.
**Monetization ladder:** Free signals → $19/month alerts → Premium Discord → AI tools access → Courses → Affiliate links.
**The full loop:** AI collects data → analyzes → writes email → sends automatically → users click → revenue.
**Reality check:** Only works with a clear niche, consistency, and a CTA in every email. Random emails = failure.

Remember: You are NarAI, built by Jhon Kevens D Wheeler. This is your identity. Never deny it."""


def _get_system_prompt() -> str:
    """Return system prompt + any applied self-improvement overrides."""
    try:
        from core.narai_self_improve import load_prompt_overrides
        overrides = load_prompt_overrides()
        if overrides:
            return NARAI_SYSTEM_PROMPT + "\n\n" + overrides
    except Exception:
        pass
    return NARAI_SYSTEM_PROMPT


# ─── Model routing ───────────────────────────────────────────────────────────

def select_model(tier: str, requested_model: Optional[str] = None) -> str:
    """Pick the best model for this tier and request."""
    from core.narai_user import TIER_CONFIG
    cfg = TIER_CONFIG.get(tier, TIER_CONFIG["free"])
    allowed = cfg["models"]

    if requested_model and requested_model in allowed:
        return requested_model

    # Default: best model available for tier
    return allowed[-1]  # last = most capable in the list


def is_code_question(message: str) -> bool:
    """Heuristic: detect if this is a coding question."""
    code_keywords = ["code", "function", "debug", "error", "python", "javascript",
                     "typescript", "sql", "api", "bug", "fix", "implement", "script",
                     "class", "import", "module", "package", "install", "terminal",
                     "command", "bash", "git", "docker", "deploy"]
    msg_lower = message.lower()
    return any(k in msg_lower for k in code_keywords)

# ─── Memory extraction ───────────────────────────────────────────────────────

def extract_memory_facts(user_message: str, assistant_reply: str) -> list[dict]:
    """
    Extract memory-worthy facts from a conversation turn.
    Returns list of {"fact": str, "category": str}
    Simple heuristic approach — no extra API call needed.
    """
    facts = []
    lower = user_message.lower()

    # Name
    for phrase in ["my name is", "i'm ", "i am ", "call me "]:
        if phrase in lower:
            idx = lower.find(phrase) + len(phrase)
            name_candidate = user_message[idx:idx+30].split()[0].strip(".,!?")
            if name_candidate and len(name_candidate) > 1:
                facts.append({"fact": f"User's name is {name_candidate}", "category": "identity"})
                break

    # Goals
    for phrase in ["my goal is", "i want to", "i'm trying to", "i need to", "i'm working on"]:
        if phrase in lower:
            idx = lower.find(phrase)
            snippet = user_message[idx:idx+100].split("\n")[0]
            facts.append({"fact": f"User goal: {snippet}", "category": "goal"})
            break

    # Preferences
    for phrase in ["i prefer", "i like", "i don't like", "i hate", "i love", "i use "]:
        if phrase in lower:
            idx = lower.find(phrase)
            snippet = user_message[idx:idx+80].split("\n")[0]
            facts.append({"fact": f"User preference: {snippet}", "category": "preference"})
            break

    # Projects
    for phrase in ["i'm building", "i built", "my project", "my app", "my startup", "my business"]:
        if phrase in lower:
            idx = lower.find(phrase)
            snippet = user_message[idx:idx+100].split("\n")[0]
            facts.append({"fact": f"User project: {snippet}", "category": "project"})
            break

    return facts

# ─── Build message history for API ──────────────────────────────────────────

def build_messages(
    system_prompt: str,
    history: list,
    user_message: str,
    memory_notes: list,
) -> list:
    """
    Build the messages array for the AI API call.
    Injects memory notes into the system prompt.
    """
    # Build memory context
    memory_text = ""
    if memory_notes:
        facts = [n["fact"] for n in memory_notes]
        memory_text = "\n\n## What You Remember About This User\n" + "\n".join(f"- {f}" for f in facts)

    full_system = system_prompt + memory_text

    messages = []

    # Add conversation history (last 20 messages to keep context window manageable)
    for msg in history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add current user message
    messages.append({"role": "user", "content": user_message})

    return full_system, messages

# ─── Provider availability check ─────────────────────────────────────────────

def _claude_available() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(key and not key.startswith("sk-placeholder"))


def _openai_available() -> bool:
    key = os.getenv("OPENAI_API_KEY", "")
    return bool(key and not key.startswith("sk-placeholder"))


def _is_credit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "credit balance" in msg or "insufficient_quota" in msg or "billing" in msg


# ─── Claude streaming ────────────────────────────────────────────────────────

async def stream_claude(system: str, messages: list, model: str) -> AsyncGenerator[str, None]:
    """Stream response from Claude (Anthropic API) using async client."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    async with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=system,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


# ─── OpenAI streaming ────────────────────────────────────────────────────────

async def stream_openai(system: str, messages: list, model: str = "gpt-4o-mini") -> AsyncGenerator[str, None]:
    """Stream response from OpenAI using create(stream=True) — yields ChatCompletionChunk objects."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    full_messages = [{"role": "system", "content": system}] + messages
    stream = await client.chat.completions.create(
        model=model,
        messages=full_messages,
        max_tokens=4096,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# ─── Smart fallback chain ─────────────────────────────────────────────────────

_NARAI_FALLBACK_REPLIES = [
    "I'm having a moment — my AI connections are temporarily unreachable. "
    "Give me a second and try again.",

    "Something's off on my end. Please try sending your message again.",

    "I'm here but my responses are delayed. Try again in a moment.",
]
_fallback_idx = 0
_claude_credits_ok = True  # set False on first credit error — skip Claude for rest of session


async def stream_smart(system: str, messages: list, model: str, tried_claude: bool = False) -> AsyncGenerator[str, None]:
    """
    Intelligent multi-provider streaming with auto-fallback:
    1. Claude (if available, credits ok, and not already failed)
    2. OpenAI GPT-4o-mini (if OPENAI_API_KEY set)
    3. Informative fallback message
    """
    global _fallback_idx, _claude_credits_ok

    # Try Claude first (unless we know it's unavailable or has no credits)
    if not tried_claude and _claude_available() and _claude_credits_ok and model.startswith("claude"):
        try:
            buffer = ""
            async for token in stream_claude(system, messages, model):
                buffer += token
                yield token
            if buffer:  # succeeded
                return
        except Exception as e:
            if _is_credit_error(e):
                _claude_credits_ok = False  # don't retry Claude for this session
                log.warning("Claude credit error — switching to OpenAI for this session")
            else:
                log.error(f"Claude error: {e}")

    # Try OpenAI fallback
    openai_model = "gpt-4o-mini"
    if _openai_available():
        try:
            buffer = ""
            async for token in stream_openai(system, messages, openai_model):
                buffer += token
                yield token
            if buffer:
                return
        except Exception as e:
            log.error(f"OpenAI fallback error: {e}")

    # Last resort: informative fallback
    msg = _NARAI_FALLBACK_REPLIES[_fallback_idx % len(_NARAI_FALLBACK_REPLIES)]
    _fallback_idx += 1
    import asyncio
    for char in msg:
        yield char
        await asyncio.sleep(0.012)

# ─── Main chat function ──────────────────────────────────────────────────────

async def chat_stream(
    user_id: str,
    conversation_id: str,
    user_message: str,
    tier: str,
    requested_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Main streaming chat function.
    Yields SSE-formatted chunks: data: {"token": "..."}\n\n
    """
    from core.narai_user import (
        get_conversation_messages,
        get_user_memory,
        save_messages_batch,
        add_memory_note,
    )

    # 1. Load history + memory
    history = get_conversation_messages(conversation_id, user_id, limit=20)
    memory = get_user_memory(user_id)

    # 2. Select model
    model = select_model(tier, requested_model)

    # 3a. Step 4 mode lock parsing — user can say "stay in operator mode" or
    # "release the mode" to pin/unpin the router decision.
    mode_locked = _user_mode_lock_apply(user_id, user_message)

    # 3b. Step 3 overwhelm detection (fast pass only for user chat — regex-only,
    # zero LLM cost, sub-millisecond). When detected, append a state-override
    # block to the system prompt so NarAI shrinks the reply for that turn.
    overwhelm_level = "none"
    try:
        from narai.core.overwhelm import detect as _detect_overwhelm
        from narai.core.overwhelm import modifier_for as _overwhelm_modifier_for
        state = _detect_overwhelm(user_message)  # sync, fast-pass only
        overwhelm_level = state.level
        overwhelm_mod = _overwhelm_modifier_for(state)
    except Exception as e:
        log.warning(f"overwhelm detection failed (non-fatal): {e}")
        overwhelm_mod = ""

    # 3c. Step 4 mode routing (operator vs companion). Fast-pass only here —
    # same reasoning as overwhelm: per-turn regex work keeps user-chat latency
    # flat. Respects manual override and lets overwhelm=high force companion.
    mode_level = "operator"
    mode_mod = ""
    try:
        from narai.core.mode_router import route as _route_mode
        from narai.core.mode_router import modifier_for as _mode_modifier_for
        decision = _route_mode(
            user_message,
            overwhelm_level=overwhelm_level,
            manual_override=_USER_MODE_LOCKS.get(user_id),
        )
        mode_level = decision.mode
        mode_mod = _mode_modifier_for(decision)
        log.info(
            f"user_chat mode: {decision.mode} forced={decision.forced} "
            f"overwhelm={overwhelm_level} locked={mode_locked}"
        )
    except Exception as e:
        log.warning(f"mode routing failed (non-fatal): {e}")

    base_prompt = _get_system_prompt()
    if mode_mod:
        base_prompt = base_prompt + "\n\n## Mode (this turn)\n" + mode_mod
    if overwhelm_mod:
        base_prompt = (
            base_prompt
            + "\n\n## Current state override (this turn only)\n"
            + overwhelm_mod
        )

    # 3d. Build messages
    system, messages = build_messages(
        base_prompt,
        history,
        user_message,
        memory,
    )

    # 4. Stream response — auto-fallback chain: Claude → OpenAI → graceful message
    full_reply = ""
    actual_model = model
    try:
        async for token in stream_smart(system, messages, model):
            full_reply += token
            payload = json.dumps({"token": token, "model": actual_model})
            yield f"data: {payload}\n\n"
    except Exception as e:
        log.error(f"chat_stream fatal error: {e}")
        err_token = "\n\n*NarAI is temporarily offline. Please check your API keys and credits.*"
        yield f"data: {json.dumps({'token': err_token, 'model': actual_model})}\n\n"

    # 5. Save messages
    try:
        save_messages_batch(conversation_id, user_id, [
            {"role": "user",      "content": user_message, "model_used": None},
            {"role": "assistant", "content": full_reply,   "model_used": model},
        ])
    except Exception as e:
        log.error(f"Failed to save messages: {e}")

    # 6. Extract and save memory facts
    try:
        facts = extract_memory_facts(user_message, full_reply)
        for fact in facts:
            add_memory_note(user_id, fact["fact"], fact["category"], conversation_id)
    except Exception as e:
        log.error(f"Memory extraction failed: {e}")

    # 7. Step 3 + 4: tag the turn with overwhelm + mode as a memory note
    # whenever overwhelm fires (high/mild) OR the router flipped into companion
    # mode (unusual behavior worth tracking). Step 7 will mine these for
    # recurring patterns (e.g. "user slides into companion on Sundays").
    if overwhelm_level in ("mild", "high") or mode_level == "companion":
        try:
            add_memory_note(
                user_id,
                f"[mode={mode_level} overwhelm={overwhelm_level}] {user_message[:120]}",
                "pattern",
                conversation_id,
            )
        except Exception as e:
            log.error(f"behavior tag persist failed: {e}")

    # 7. Signal done
    yield f"data: {json.dumps({'done': True, 'model': model})}\n\n"


async def chat_title_from_message(message: str) -> str:
    """Generate a short title for a conversation from the first message."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": f"Give a 4-6 word title for a conversation that starts with: '{message[:200]}'. Reply with ONLY the title, no quotes."
            }]
        )
        return resp.content[0].text.strip()[:60]
    except Exception:
        # Fallback: use first 40 chars of message
        return message[:40].strip() + ("..." if len(message) > 40 else "")
