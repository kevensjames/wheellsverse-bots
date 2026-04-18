"""Skill pack loader. Skills are .md files in narai/skills/.
Active skill is prepended to the system prompt on every LLM call."""
import os
from pathlib import Path
from typing import Iterator

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_ACTIVE_SKILL: str | None = None
_CACHE: dict[str, str] = {}


def _load(name: str) -> str:
    if name not in _CACHE:
        path = _SKILLS_DIR / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Skill not found: {name}")
        _CACHE[name] = path.read_text(encoding="utf-8")
    return _CACHE[name]


def available() -> list[str]:
    return [p.stem for p in _SKILLS_DIR.glob("*.md")]


def activate(name: str) -> str:
    """Set the active skill. Returns the skill prompt."""
    global _ACTIVE_SKILL
    content = _load(name)  # validates existence
    _ACTIVE_SKILL = name
    _CACHE.pop(name, None)  # clear cache so hot-reload picks up edits
    _CACHE[name] = _load(name)
    return content


def deactivate() -> None:
    global _ACTIVE_SKILL
    _ACTIVE_SKILL = None


def active_prompt() -> str | None:
    """Return the current skill's system prompt, or None if no skill is active."""
    if _ACTIVE_SKILL is None:
        return None
    try:
        return _load(_ACTIVE_SKILL)
    except FileNotFoundError:
        return None


def build_system_prompt(
    base: str | None = None,
    skill: str | None = None,
    memory_context: str | None = None,
    rag_context: str | None = None,
) -> str:
    """Assemble the full system prompt: skill + base + memory + rag."""
    parts: list[str] = []
    skill_name = skill or _ACTIVE_SKILL
    if skill_name:
        try:
            parts.append(_load(skill_name))
        except FileNotFoundError:
            pass
    if base:
        parts.append(base)
    if memory_context:
        parts.append(memory_context)
    if rag_context:
        parts.append(rag_context)
    return "\n\n---\n\n".join(filter(None, parts))
