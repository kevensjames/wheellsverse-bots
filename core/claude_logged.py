"""Single-source-of-truth wrapper for Anthropic API calls.

Every code path that previously did:

    client = anthropic.Anthropic(api_key=...)
    resp = client.messages.create(model=..., max_tokens=..., messages=...)

should call this instead:

    from core.claude_logged import create as claude_create
    resp = claude_create(model=..., max_tokens=..., messages=..., bot_name="my_bot")

Three jobs in one place:

  1. **Daily-budget guard.** Reads `_DAILY_BUDGET_USD` from env via base_bot;
     raises `BudgetExceededError` before the API call when today's spend ≥ cap.
     Without this wrapper, individual call sites bypass the cap silently.

  2. **Token logging.** Appends to data/token_usage.json with bot_name
     attribution. Required for the per-bot spend report and the
     `_get_today_anthropic_spend()` accounting that base_bot.py uses.

  3. **Credit-balance error normalization.** If Anthropic returns "credit
     balance too low", we re-raise as `BudgetExceededError` so callers can
     handle the operator condition without parsing string errors.

Local-backend support (LLM_BACKEND=ollama):
    When LLM_BACKEND is set, calls are translated to an OpenAI-compatible
    local server (Ollama default) and the response is wrapped in a shim
    that quacks like `anthropic.types.Message` so callers using
    `resp.content[0].text` keep working unchanged. The daily-budget guard
    and Anthropic credit-balance handling are short-circuited on the
    local path (no spend, no credit balance).

Returns the raw `anthropic.types.Message` object — callers using
`resp.content[0].text` don't need to change anything except the `client.`
prefix.
"""
from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger("claude_logged")


def _is_local_backend() -> bool:
    backend = (os.getenv("LLM_BACKEND") or "").strip().lower()
    return backend in ("ollama", "local", "lmstudio", "llamacpp")


def _local_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def _map_model(model: str) -> str:
    """Translate an Anthropic model name to a local Ollama tag.

    Source: OLLAMA_MODEL_MAP env var (JSON). Unknown models pass through.
    """
    raw = os.getenv("OLLAMA_MODEL_MAP", "").strip()
    if not raw:
        return model
    try:
        return json.loads(raw).get(model, model)
    except json.JSONDecodeError:
        logger.warning("OLLAMA_MODEL_MAP is not valid JSON — passing model through")
        return model


def _translate_tools_to_openai(anthropic_tools: list) -> list:
    """Convert Anthropic-shape tool definitions to OpenAI-shape.

    Anthropic: [{name, description, input_schema}]
    OpenAI:    [{type:"function", function:{name, description, parameters}}]
    """
    out: list = []
    for t in anthropic_tools or []:
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _translate_messages_for_openai(messages: list) -> list:
    """Translate Anthropic-shape messages (including tool_use / tool_result blocks)
    into OpenAI chat-completion shape.

    Anthropic assistant w/ tool_use:
        {role:"assistant", content:[{type:"text",text}, {type:"tool_use", id, name, input}]}
    → OpenAI:
        {role:"assistant", content:"<text>", tool_calls:[{id, type:"function",
                                                          function:{name, arguments:<JSON str>}}]}

    Anthropic user w/ tool_result:
        {role:"user", content:[{type:"tool_result", tool_use_id, content}]}
    → OpenAI:
        {role:"tool", tool_call_id, content} (one message per tool_result)
    """
    out: list = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")

        # Simple string content — no translation needed.
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        # Anthropic-shape: content is a list of blocks. Anthropic SDK objects
        # have .type/.text/.name/.input/.id attrs; serialised dicts use keys.
        if not isinstance(content, list):
            out.append({"role": role, "content": str(content)})
            continue

        # Pull out the parts by type.
        text_parts: list = []
        tool_uses: list = []
        tool_results: list = []
        for block in content:
            # Support both dict and SDK-object form.
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "text":
                txt = block.get("text") if isinstance(block, dict) else getattr(block, "text", "")
                text_parts.append(txt or "")
            elif btype == "tool_use":
                tu_id = block.get("id") if isinstance(block, dict) else getattr(block, "id", "")
                tu_name = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
                tu_input = block.get("input") if isinstance(block, dict) else getattr(block, "input", {})
                tool_uses.append({
                    "id": tu_id,
                    "type": "function",
                    "function": {
                        "name": tu_name,
                        "arguments": json.dumps(tu_input or {}),
                    },
                })
            elif btype == "tool_result":
                tr_id = block.get("tool_use_id") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                tr_content = block.get("content") if isinstance(block, dict) else getattr(block, "content", "")
                if isinstance(tr_content, list):
                    tr_content = "".join(
                        (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                        for b in tr_content
                    )
                tool_results.append({"tool_call_id": tr_id, "content": str(tr_content)})

        if tool_results:
            # tool_result blocks → one OpenAI tool message each (role=tool).
            for tr in tool_results:
                out.append({"role": "tool", "tool_call_id": tr["tool_call_id"], "content": tr["content"]})
        else:
            joined_text = "".join(text_parts)
            msg: dict = {"role": role, "content": joined_text}
            if tool_uses:
                msg["tool_calls"] = tool_uses
            out.append(msg)
    return out


def _anthropic_shim(openai_resp: Any) -> Any:
    """Wrap an OpenAI chat-completion response so it looks like an Anthropic Message.

    Anthropic callers read `resp.content[0].text` and `resp.usage.input_tokens` /
    `output_tokens`. OpenAI exposes `resp.choices[0].message.content` and
    `resp.usage.prompt_tokens` / `completion_tokens`. We build a SimpleNamespace
    with both attribute paths populated, then return it. Callers that use either
    shape keep working.

    Tool calling: when the OpenAI response contains tool_calls, we translate
    them into Anthropic tool_use content blocks and set stop_reason="tool_use".
    """
    choice = openai_resp.choices[0] if openai_resp.choices else None
    msg = getattr(choice, "message", None) if choice else None
    text = (getattr(msg, "content", "") or "") if msg else ""

    content_blocks: list = []
    if text:
        content_blocks.append(SimpleNamespace(type="text", text=text))

    # Translate tool_calls → Anthropic tool_use blocks.
    tool_calls = getattr(msg, "tool_calls", None) if msg else None
    has_tool_use = False
    if tool_calls:
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            tc_name = getattr(fn, "name", "") if fn else ""
            tc_args_raw = getattr(fn, "arguments", "{}") if fn else "{}"
            try:
                tc_input = json.loads(tc_args_raw) if tc_args_raw else {}
            except (json.JSONDecodeError, TypeError):
                tc_input = {"_raw": str(tc_args_raw)}
            content_blocks.append(SimpleNamespace(
                type="tool_use",
                id=getattr(tc, "id", "") or "",
                name=tc_name,
                input=tc_input,
            ))
            has_tool_use = True

    if not content_blocks:
        content_blocks.append(SimpleNamespace(type="text", text=""))

    in_tok = 0
    out_tok = 0
    usage = getattr(openai_resp, "usage", None)
    if usage is not None:
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0

    # Map OpenAI finish_reason to Anthropic stop_reason. Tool-use takes priority.
    if has_tool_use:
        stop_reason = "tool_use"
    else:
        finish = getattr(choice, "finish_reason", "stop") if choice else "stop"
        stop_reason = "end_turn" if finish == "stop" else finish

    return SimpleNamespace(
        content=content_blocks,
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        stop_reason=stop_reason,
        model=getattr(openai_resp, "model", ""),
        role="assistant",
    )


def _call_local(
    model: str,
    max_tokens: int,
    messages: list,
    system: Optional[str],
    extra: dict,
) -> Any:
    """Issue the call against the local OpenAI-compatible server and shim the response.

    Handles tool-calling translation when `tools` is in extra:
      - Anthropic tool definitions → OpenAI function definitions
      - Anthropic tool_use/tool_result content blocks → OpenAI tool_calls/tool messages
      - OpenAI tool_calls response → Anthropic tool_use content blocks (via _anthropic_shim)
    """
    import openai

    effective_model = _map_model(model)

    # Anthropic uses a top-level `system` arg; OpenAI puts it as the first
    # message. Prepend if present.
    oa_messages: list = []
    if system:
        oa_messages.append({"role": "system", "content": system})
    oa_messages.extend(_translate_messages_for_openai(messages))

    # Translate Anthropic-shape tools → OpenAI function definitions.
    safe_extra = dict(extra)
    raw_tools = safe_extra.pop("tools", None)
    if raw_tools:
        # If tools are already in OpenAI shape (have "type":"function"), pass through.
        first = raw_tools[0] if raw_tools else None
        if isinstance(first, dict) and first.get("type") == "function":
            safe_extra["tools"] = raw_tools
        else:
            safe_extra["tools"] = _translate_tools_to_openai(raw_tools)
    # Drop Anthropic-only kwargs that OpenAI/Ollama won't accept.
    for k in ("anthropic_version", "metadata", "tool_choice"):
        # tool_choice has different enums between providers; drop unless caller
        # explicitly opts in via OpenAI-shape value.
        if k == "tool_choice" and isinstance(safe_extra.get(k), (dict, str)):
            continue
        safe_extra.pop(k, None)

    client = openai.OpenAI(
        base_url=_local_base_url(),
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
    )
    resp = client.chat.completions.create(
        model=effective_model,
        messages=oa_messages,
        max_tokens=max_tokens,
        **safe_extra,
    )
    return _anthropic_shim(resp)


def create(
    *,
    model: str,
    max_tokens: int,
    messages: list,
    system: Optional[str] = None,
    bot_name: str = "unknown",
    api_key: Optional[str] = None,
    **extra: Any,
) -> Any:
    """Drop-in for `anthropic_client.messages.create(...)`.

    Differences vs raw SDK call:
      - Pre-flight daily-budget check (BudgetExceededError if blown)
      - Pre-flight credit-balance error → BudgetExceededError
      - Post-call token logging via core.base_bot._log_token_usage
    """
    # Lazy imports so this module stays cheap to import.
    from core.base_bot import (
        BudgetExceededError, _DAILY_BUDGET_USD,
        _get_today_anthropic_spend, _log_token_usage,
    )

    # LOCAL PATH: route to Ollama and shim the response. No budget guard,
    # no credit balance — those are cloud-cost artifacts.
    if _is_local_backend():
        resp = _call_local(model, max_tokens, messages, system, extra)
        # Still log usage for parity with cloud accounting (cost will be $0).
        try:
            usage = getattr(resp, "usage", None)
            if usage is not None:
                _log_token_usage(
                    "ollama",
                    _map_model(model),
                    getattr(usage, "input_tokens", 0) or 0,
                    getattr(usage, "output_tokens", 0) or 0,
                    bot_name,
                )
        except Exception as log_err:
            logger.warning(f"token logging failed for {bot_name}: {log_err}")
        return resp

    spend = _get_today_anthropic_spend()
    if spend >= _DAILY_BUDGET_USD:
        raise BudgetExceededError(
            f"Daily Anthropic budget (${_DAILY_BUDGET_USD:.2f}) reached "
            f"(spent ${spend:.4f}) — call from {bot_name!r} blocked"
        )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""))
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages, **extra}
    if system is not None:
        kwargs["system"] = system

    try:
        resp = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        msg = str(e).lower()
        if "credit balance" in msg or "credit_balance" in msg:
            raise BudgetExceededError(
                "Anthropic credit balance too low — top up at "
                "console.anthropic.com/settings/billing"
            ) from e
        raise

    # Log usage. Failures here must not break the caller.
    try:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            _log_token_usage(
                "anthropic",
                model,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                bot_name,
            )
    except Exception as log_err:
        logger.warning(f"token logging failed for {bot_name}: {log_err}")

    return resp


def is_budget_healthy() -> bool:
    """Cheap pre-flight check: is today's Anthropic spend below the daily cap?

    Use this at the top of long-running jobs (cron-triggered autopilots) to
    skip cleanly instead of generating a cascade of credit-balance errors.

    Note: this only checks the *daily budget* heuristic. Anthropic-side credit
    balance can still be empty even if our daily-budget accounting says OK —
    that case is caught by `create()` raising `BudgetExceededError` on the
    actual API response.

    Local backend is always healthy (free inference, no cap).
    """
    if _is_local_backend():
        return True
    try:
        from core.base_bot import _DAILY_BUDGET_USD, _get_today_anthropic_spend
        return _get_today_anthropic_spend() < _DAILY_BUDGET_USD
    except Exception:
        # If the helpers blow up, default to "healthy" so we don't accidentally
        # disable everything on an unrelated error.
        return True
