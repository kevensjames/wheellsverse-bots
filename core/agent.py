#!/usr/bin/env python3
"""
core/agent.py
─────────────────────────────────────────────────────────────────────────────
NarAI Autonomous Agent — multi-step task execution via Claude tool_use.

Loop: think → pick tool → run tool → observe → repeat (max 10 iterations)
Streams each step to a callback for SSE delivery.

Available tools:
  web_search      — DuckDuckGo search
  run_bot         — Start/stop/restart bots via bot_manager
  generate_code   — Generate Python code via code_engine
  read_file       — Read a file inside the project
  write_file      — Write a file inside the project (sandboxed)
  shell_command   — Run a safe shell command (sandboxed allowlist)
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import anthropic

logger = logging.getLogger("agent")

ROOT = Path(__file__).parent.parent
_MODEL = os.getenv("AGENT_MODEL", os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))
_MAX_ITER = 10

# ─── Active agent registry ────────────────────────────────────────────────────
_active_agents: Dict[str, asyncio.Task] = {}
_agent_history: Dict[str, List[Dict]] = {}   # run_id → list of step dicts


# ─── Tool schemas ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for current information using DuckDuckGo. Use this for news, prices, facts, or anything requiring up-to-date data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "num_results": {"type": "integer", "description": "Number of results (1-10)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_bot",
        "description": "Start, stop, restart, or list bots in the WheellsVerse ecosystem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start", "stop", "restart", "list", "status"], "description": "Action to perform"},
                "bot_name": {"type": "string", "description": "Bot name (required for start/stop/restart/status)"},
                "category": {"type": "string", "description": "Bot category folder (required for start)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "generate_code",
        "description": "Generate Python bot code using Claude. The code is validated and saved to generated_bots/.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Description of what the bot should do"},
                "save_as": {"type": "string", "description": "Filename to save as (without .py)"},
            },
            "required": ["prompt", "save_as"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file in the WheellsVerse project directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root (e.g. core/api.py)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the WheellsVerse project directory. Only allowed in generated_bots/ and data/ folders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "shell_command",
        "description": "Run a safe shell command. Only a small allowlist is permitted: ls, cat, head, tail, grep, wc, find, python3 -c, pip show.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
]

# ─── Tool implementations ─────────────────────────────────────────────────────


def _tool_web_search(args: dict) -> str:
    try:
        from core.search_engine import run_search
        result = run_search(args["query"], args.get("num_results", 5))
        return result["context"]
    except Exception as e:
        return f"Search error: {e}"


def _tool_run_bot(args: dict) -> str:
    try:
        from core.bot_manager import start_bot, stop_bot, restart_bot, list_bots, bot_status
        action = args["action"]
        name = args.get("bot_name", "")
        if action == "list":
            bots = list_bots()
            if not bots:
                return "No bots currently running."
            return json.dumps(bots, indent=2)
        elif action == "start":
            result = start_bot(name, args.get("category", ""))
            return json.dumps(result)
        elif action == "stop":
            result = stop_bot(name)
            return json.dumps(result)
        elif action == "restart":
            result = restart_bot(name)
            return json.dumps(result)
        elif action == "status":
            result = bot_status(name)
            return json.dumps(result)
        return "Unknown action"
    except Exception as e:
        return f"Bot action error: {e}"


def _tool_generate_code(args: dict) -> str:
    try:
        from core.code_engine import generate_code, validate_code, save_code
        code = generate_code(args["prompt"])
        valid, err = validate_code(code)
        if not valid:
            return f"Generated code has syntax error: {err}"
        path = save_code(args["save_as"], code)
        return f"Code generated and saved to {path}\n\nPreview (first 20 lines):\n" + "\n".join(code.splitlines()[:20])
    except Exception as e:
        return f"Code generation error: {e}"


def _tool_read_file(args: dict) -> str:
    try:
        rel = args["path"].lstrip("/")
        full = ROOT / rel
        # Security: must be inside project root
        full.resolve().relative_to(ROOT.resolve())
        if not full.exists():
            return f"File not found: {rel}"
        content = full.read_text(errors="replace")
        if len(content) > 8000:
            content = content[:8000] + f"\n\n[...truncated, {len(content)} total chars]"
        return content
    except ValueError:
        return "Access denied: path outside project directory"
    except Exception as e:
        return f"Read error: {e}"


_WRITE_ALLOWED = ("generated_bots/", "data/", "bots_backup/", "uploads/")


def _tool_write_file(args: dict) -> str:
    try:
        rel = args["path"].lstrip("/")
        if not any(rel.startswith(prefix) for prefix in _WRITE_ALLOWED):
            return f"Write denied: only allowed in {', '.join(_WRITE_ALLOWED)}"
        full = ROOT / rel
        full.resolve().relative_to(ROOT.resolve())
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(args["content"])
        return f"Written {len(args['content'])} bytes to {rel}"
    except ValueError:
        return "Access denied: path outside project directory"
    except Exception as e:
        return f"Write error: {e}"


_SHELL_ALLOWLIST = {"ls", "cat", "head", "tail", "grep", "wc", "find", "python3", "pip"}
_SHELL_BLOCKED_CHARS = (";", "&", "|", "`", "$", ">", "<", "\n", "\r")


def _tool_shell_command(args: dict) -> str:
    import shlex
    cmd = args["command"].strip()
    if any(c in cmd for c in _SHELL_BLOCKED_CHARS):
        return "Command rejected: shell metacharacters not allowed"
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return f"Command parse error: {e}"
    if not parts:
        return "Empty command"
    program = parts[0]
    if program not in _SHELL_ALLOWLIST:
        return f"Command not allowed. Permitted programs: {', '.join(sorted(_SHELL_ALLOWLIST))}"
    if program == "python3" and (len(parts) < 2 or parts[1] != "-c"):
        return "python3 only allowed with -c flag"
    if program == "pip" and (len(parts) < 2 or parts[1] != "show"):
        return "pip only allowed with 'show' subcommand"
    try:
        result = subprocess.run(
            parts, shell=False, capture_output=True, text=True,
            cwd=str(ROOT), timeout=15
        )
        out = (result.stdout + result.stderr).strip()
        return out[:4000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 15 seconds"
    except Exception as e:
        return f"Shell error: {e}"


_TOOL_DISPATCH = {
    "web_search": _tool_web_search,
    "run_bot": _tool_run_bot,
    "generate_code": _tool_generate_code,
    "read_file": _tool_read_file,
    "write_file": _tool_write_file,
    "shell_command": _tool_shell_command,
}


def _execute_tool(name: str, args: dict) -> str:
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    return fn(args)


# ─── Agent loop ───────────────────────────────────────────────────────────────

async def run_agent(
    task: str,
    run_id: str,
    conv_id: Optional[str] = None,
    stream_cb: Optional[Callable[[dict], None]] = None,
) -> List[Dict]:
    """
    Run the autonomous agent loop.
    Streams step dicts to stream_cb and stores in _agent_history[run_id].

    Returns the full step history.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    _agent_history[run_id] = []

    def _emit(step: dict):
        _agent_history[run_id].append(step)
        if stream_cb:
            try:
                stream_cb(step)
            except Exception:
                pass

    system = (
        "You are NarAI, an autonomous AI agent for the WheellsVerse platform. "
        "You have access to tools to search the web, manage bots, generate code, read/write files, "
        "and run shell commands. Complete the user's task step by step. "
        "Think carefully before each tool call. When you have enough information, "
        "summarize your findings and mark the task as done."
    )

    messages: List[Dict[str, Any]] = [{"role": "user", "content": task}]

    _emit({"type": "start", "task": task, "run_id": run_id})

    for iteration in range(_MAX_ITER):
        try:
            response = await asyncio.to_thread(
                lambda: client.messages.create(
                    model=_MODEL,
                    max_tokens=4096,
                    system=system,
                    tools=TOOLS,
                    messages=messages,
                )
            )
        except Exception as e:
            _emit({"type": "error", "message": str(e), "iteration": iteration})
            break

        # Collect all content blocks
        assistant_content = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                if block.text.strip():
                    _emit({"type": "thinking", "text": block.text, "iteration": iteration})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                tool_uses.append(block)

        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn" or not tool_uses:
            # Final answer
            final_text = " ".join(
                b["text"] for b in assistant_content if b.get("type") == "text"
            ).strip()
            _emit({"type": "done", "result": final_text, "iterations": iteration + 1})
            break

        # Execute all tool calls
        tool_results = []
        for block in tool_uses:
            _emit({
                "type": "tool_call",
                "tool": block.name,
                "input": block.input,
                "iteration": iteration,
            })

            output = await asyncio.to_thread(_execute_tool, block.name, block.input)

            _emit({
                "type": "tool_result",
                "tool": block.name,
                "output": output[:2000] if len(output) > 2000 else output,
                "iteration": iteration,
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        messages.append({"role": "user", "content": tool_results})

    else:
        _emit({"type": "done", "result": "Reached maximum iterations.", "iterations": _MAX_ITER})

    return _agent_history[run_id]


# ─── Public API ───────────────────────────────────────────────────────────────

def start_agent(task: str, conv_id: Optional[str] = None) -> str:
    """
    Launch agent as background asyncio task.
    Returns run_id immediately.
    """
    run_id = str(uuid.uuid4())

    async def _run():
        await run_agent(task, run_id, conv_id)

    loop = asyncio.get_event_loop()
    task_obj = loop.create_task(_run())
    _active_agents[run_id] = task_obj

    def _cleanup(fut):
        _active_agents.pop(run_id, None)

    task_obj.add_done_callback(_cleanup)
    return run_id


def cancel_agent(run_id: str) -> bool:
    """Cancel a running agent task. Returns True if cancelled."""
    task_obj = _active_agents.get(run_id)
    if task_obj and not task_obj.done():
        task_obj.cancel()
        _active_agents.pop(run_id, None)
        _agent_history.setdefault(run_id, []).append(
            {"type": "cancelled", "run_id": run_id}
        )
        return True
    return False


def get_history(run_id: str) -> List[Dict]:
    """Return accumulated step history for a run."""
    return _agent_history.get(run_id, [])


def list_agents() -> List[Dict]:
    """List all active and recent agent runs."""
    result = []
    for rid, task_obj in _active_agents.items():
        result.append({
            "run_id": rid,
            "status": "running" if not task_obj.done() else "done",
            "steps": len(_agent_history.get(rid, [])),
        })
    # Include recently completed (in history but not in active)
    for rid, steps in _agent_history.items():
        if rid not in _active_agents:
            done_step = next((s for s in reversed(steps) if s.get("type") in ("done", "error", "cancelled")), None)
            result.append({
                "run_id": rid,
                "status": done_step["type"] if done_step else "unknown",
                "steps": len(steps),
                "task": next((s.get("task", "") for s in steps if s.get("type") == "start"), ""),
            })
    return result
