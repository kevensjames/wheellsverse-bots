#!/usr/bin/env python3
"""
core/code_engine.py
─────────────────────────────────────────────────────────────────────────────
AI-powered code generation, saving, and subprocess execution with streaming.
─────────────────────────────────────────────────────────────────────────────
"""

import ast
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, Generator, Optional, Tuple

logger = logging.getLogger("code_engine")

ROOT = Path(__file__).parent.parent
PYTHON = ROOT / "venv" / "bin" / "python3"
GENERATED_DIR = ROOT / "generated_bots"
BACKUP_DIR = ROOT / "bots_backup"

GENERATED_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

_CODE_MODEL = os.getenv("CODE_ENGINE_MODEL", os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"))

# ─── Active runs registry ──────────────────────────────────────────────────────
# key: run_id (UUID str) → Popen
_active_runs: Dict[str, subprocess.Popen] = {}

# ─── System prompt ────────────────────────────────────────────────────────────
_CODE_SYSTEM = """\
You are an expert Python bot developer for the WheellsVerse platform.
Generate clean, runnable Python bot code that follows the BaseBot pattern.

Rules:
- Return ONLY the raw Python code — no markdown fences, no explanations.
- The bot must be self-contained and runnable with `python3 bot.py`.
- Import from `core.base_bot` if inheriting BaseBot.
- Use `if __name__ == "__main__":` to run the bot.
- Keep code concise and production-ready.
"""

# ─── Code generation ─────────────────────────────────────────────────────────


def generate_code(prompt: str, template: Optional[str] = None) -> str:
    """
    Call Claude to generate Python bot code.
    Returns raw Python string (no markdown).
    Raises RuntimeError on API failure.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    client = Anthropic(api_key=api_key)

    user_content = prompt
    if template:
        user_content = f"{prompt}\n\nBase template to extend:\n```python\n{template}\n```"

    response = client.messages.create(
        model=_CODE_MODEL,
        max_tokens=4096,
        system=_CODE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )

    code = response.content[0].text.strip()

    # Strip markdown fences if Claude included them anyway
    if code.startswith("```"):
        lines = code.splitlines()
        code = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    logger.info(f"[code_engine] Generated {len(code)} chars for prompt: {prompt[:80]}...")
    return code


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_code(code: str) -> Tuple[bool, str]:
    """
    Validate Python syntax via compile() + ast.parse().
    Returns (is_valid, error_message).
    """
    try:
        compile(code, "<generated>", "exec")
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


# ─── Save / backup ────────────────────────────────────────────────────────────

def save_code(name: str, code: str) -> Path:
    """
    Save code to generated_bots/{name}.py.
    If the file already exists, backs it up to bots_backup/{name}_{ts}.py first.
    Returns the saved path.
    """
    # Sanitize name
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
    if not safe_name:
        safe_name = "bot"

    dest = GENERATED_DIR / f"{safe_name}.py"

    if dest.exists():
        ts = int(time.time())
        backup = BACKUP_DIR / f"{safe_name}_{ts}.py"
        shutil.copy2(dest, backup)
        logger.info(f"[code_engine] Backed up existing {dest.name} → {backup.name}")

    dest.write_text(code, encoding="utf-8")
    logger.info(f"[code_engine] Saved code to {dest}")
    return dest


# ─── Execution ────────────────────────────────────────────────────────────────

def run_code(path: str) -> str:
    """
    Launch a Python file in a subprocess with piped stdout+stderr.
    Returns a run_id (UUID) that can be used to stream output or kill.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")

    run_id = str(uuid.uuid4())

    popen = subprocess.Popen(
        [str(PYTHON), str(file_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    _active_runs[run_id] = popen
    logger.info(f"[code_engine] Started run {run_id} for {file_path.name} (PID={popen.pid})")
    return run_id


def stream_output(run_id: str) -> Generator[str, None, None]:
    """
    Yield stdout lines for a running subprocess until it exits.
    Cleans up the run entry when done.
    """
    popen = _active_runs.get(run_id)
    if not popen:
        yield f"[error] No active run with id={run_id}\n"
        return

    try:
        for line in popen.stdout:
            yield line
    finally:
        popen.wait()
        _active_runs.pop(run_id, None)
        logger.info(f"[code_engine] Run {run_id} finished (exit={popen.returncode})")


def kill_code(run_id: str) -> bool:
    """
    Terminate an active run. Returns True if found and killed.
    """
    popen = _active_runs.get(run_id)
    if not popen:
        return False

    if popen.poll() is None:
        popen.terminate()
        try:
            popen.wait(timeout=3)
        except subprocess.TimeoutExpired:
            popen.kill()
            popen.wait()

    _active_runs.pop(run_id, None)
    logger.info(f"[code_engine] Killed run {run_id}")
    return True


# ─── File listing ─────────────────────────────────────────────────────────────

def list_generated_files() -> list:
    """Return metadata for all files in generated_bots/."""
    result = []
    for p in sorted(GENERATED_DIR.glob("*.py")):
        stat = p.stat()
        result.append({
            "name": p.stem,
            "filename": p.name,
            "path": str(p),
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    return result


def read_generated_file(name: str) -> str:
    """Read a generated bot file by name (with or without .py)."""
    safe = name.replace(".py", "")
    p = GENERATED_DIR / f"{safe}.py"
    if not p.exists():
        raise ValueError(f"File not found: {p}")
    return p.read_text(encoding="utf-8")


def active_runs() -> list:
    """Return list of currently active run IDs with their PIDs."""
    result = []
    dead = []
    for run_id, popen in _active_runs.items():
        if popen.poll() is None:
            result.append({"run_id": run_id, "pid": popen.pid, "status": "running"})
        else:
            dead.append(run_id)
    for run_id in dead:
        _active_runs.pop(run_id, None)
    return result
