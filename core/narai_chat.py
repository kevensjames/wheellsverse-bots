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
from typing import AsyncGenerator, List, Optional

log = logging.getLogger("narai.chat")

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

Remember: You are NarAI, built by Jhon Kevens D Wheeler. This is your identity. Never deny it."""

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

# ─── Claude streaming ────────────────────────────────────────────────────────

async def stream_claude(system: str, messages: list, model: str) -> AsyncGenerator[str, None]:
    """Stream response from Claude (Anthropic API)."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

        with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as e:
        log.error(f"Claude stream error: {e}")
        yield f"\n\n*[NarAI encountered an error: {e}]*"

# ─── OpenAI streaming ────────────────────────────────────────────────────────

async def stream_openai(system: str, messages: list, model: str) -> AsyncGenerator[str, None]:
    """Stream response from OpenAI."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

        full_messages = [{"role": "system", "content": system}] + messages

        async with client.chat.completions.stream(
            model=model,
            messages=full_messages,
            max_tokens=4096,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
    except Exception as e:
        log.error(f"OpenAI stream error: {e}")
        yield f"\n\n*[NarAI encountered an error: {e}]*"

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
    use_claude = model.startswith("claude")

    # 3. Build messages
    system, messages = build_messages(
        NARAI_SYSTEM_PROMPT,
        history,
        user_message,
        memory,
    )

    # 4. Stream response
    full_reply = ""
    try:
        if use_claude:
            generator = stream_claude(system, messages, model)
        else:
            generator = stream_openai(system, messages, model)

        async for token in generator:
            full_reply += token
            # Yield SSE chunk
            payload = json.dumps({"token": token, "model": model})
            yield f"data: {payload}\n\n"

    except Exception as e:
        log.error(f"chat_stream error: {e}")
        err_payload = json.dumps({"token": f"\n\n*Error: {e}*", "model": model})
        yield f"data: {err_payload}\n\n"

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
