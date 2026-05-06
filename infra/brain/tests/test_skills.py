"""Tests for skill pack loader."""
import pytest
from infra.brain import skills


def test_available_skills():
    available = skills.available()
    assert "trader" in available
    assert "coder" in available
    assert "writer" in available


def test_activate_and_prompt():
    skills.activate("trader")
    prompt = skills.active_prompt()
    assert prompt is not None
    assert "Trader Mode" in prompt


def test_deactivate():
    skills.activate("coder")
    skills.deactivate()
    assert skills.active_prompt() is None


def test_activate_unknown_raises():
    with pytest.raises(FileNotFoundError):
        skills.activate("nonexistent_skill_xyz")


def test_build_system_prompt_combines():
    result = skills.build_system_prompt(
        base="Base instructions.",
        skill="writer",
        memory_context="[MEMORY CONTEXT]\n• relevant memory",
        rag_context="[RAG CONTEXT]\n• relevant doc",
    )
    assert "Writer Mode" in result
    assert "Base instructions." in result
    assert "MEMORY CONTEXT" in result
    assert "RAG CONTEXT" in result
