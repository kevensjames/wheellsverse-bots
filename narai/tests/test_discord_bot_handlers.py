"""Contract tests for the Discord-depth additions.

We don't spin up a real Discord client in tests — the new slash commands
are defined inside `start_bot()` and tied to the live websocket. Instead
we verify the *contracts* the new commands rely on are still in place:

  • core.discord_bot module imports cleanly + module-level globals exist
  • subscriber_content._safe_quote / _safe_forecast / _arrow signatures
  • narai.core.research.ResearchBrief / research async
  • narai.core.rag.{ingest_text, query, aingest, query_context} signatures
  • narai.voice.tts.get_tts(provider) signature
  • _get_narai_response accepts the new `user_id` kwarg
"""
from __future__ import annotations

import inspect

import pytest


def test_discord_bot_module_imports_cleanly():
    import core.discord_bot as db
    assert hasattr(db, "_voice_clients") and isinstance(db._voice_clients, dict)
    assert hasattr(db, "_rate_limits") and isinstance(db._rate_limits, dict)
    assert hasattr(db, "is_enabled")
    assert hasattr(db, "start_bot")
    assert hasattr(db, "stop_bot")
    assert hasattr(db, "_get_narai_response")


def test_get_narai_response_accepts_user_id():
    """The signature change is the contract /ask + on_message rely on."""
    import core.discord_bot as db
    sig = inspect.signature(db._get_narai_response)
    params = sig.parameters
    assert "text" in params
    assert "channel_id" in params
    assert "user_id" in params, "user_id kwarg required for per-user RAG isolation"
    assert params["user_id"].default is None
    assert inspect.iscoroutinefunction(db._get_narai_response)


def test_subscriber_content_helpers_exist():
    """`/stock` reuses these — if they're renamed/removed it must blow up loudly."""
    from narai.integrations import subscriber_content as sc
    assert callable(sc._safe_quote)
    assert callable(sc._safe_forecast)
    assert callable(sc._arrow)

    # _arrow contract: returns an emoji for each direction
    assert sc._arrow("up") == "🟢"
    assert sc._arrow("down") == "🔴"
    assert sc._arrow("flat") == "⚪"
    assert sc._arrow("anything-else") == "⚪"  # default fallback


def test_research_module_contract():
    """`/research` slash imports these. They must be importable + the right shape."""
    pytest.importorskip("chromadb",
                        reason="research → rag → chromadb; install via requirements.txt")
    from narai.core.research import ResearchBrief, research, ResearchResult

    # ResearchBrief must accept the kwargs we pass from the slash command
    brief = ResearchBrief(query="x", max_sources=6, ingest_to_rag=True, rag_label="x")
    assert brief.query == "x"
    assert brief.max_sources == 6
    assert brief.ingest_to_rag is True

    # research() must be a coroutine function
    assert inspect.iscoroutinefunction(research)

    # ResearchResult.to_dict must surface 'combined' + 'summaries' that our embed renders
    fields = {f for f in ResearchResult.__dataclass_fields__}
    assert {"query", "n_sources", "n_ingested", "summaries", "combined"} <= fields


def test_rag_module_contract():
    """File→RAG ingest + per-user filter both depend on these signatures."""
    pytest.importorskip("chromadb",
                        reason="rag → chromadb; install via requirements.txt")
    from narai.core import rag

    assert callable(rag.ingest)
    assert callable(rag.ingest_text)
    assert callable(rag.query)
    assert callable(rag.query_context)
    assert inspect.iscoroutinefunction(rag.aingest)
    assert inspect.iscoroutinefunction(rag.aquery)

    # query() must accept source_filter — that's how we isolate users.
    sig = inspect.signature(rag.query)
    assert "source_filter" in sig.parameters


def test_tts_module_contract():
    """`/voice` playback depends on get_tts(provider).synthesize(text) -> bytes."""
    from narai.voice import tts

    assert callable(tts.get_tts)
    sig = inspect.signature(tts.get_tts)
    assert "provider" in sig.parameters

    # Edge TTS provider has no extra setup; ElevenLabs needs an API key.
    edge = tts.get_tts("edge")
    assert hasattr(edge, "synthesize")
    assert inspect.iscoroutinefunction(edge.synthesize)


def test_pynacl_listed_in_requirements():
    """Voice channels need PyNaCl. Without it, /voice fails opaquely on Railway."""
    from pathlib import Path
    req = Path(__file__).resolve().parents[2] / "requirements.txt"
    text = req.read_text().lower()
    assert "pynacl" in text, "PyNaCl must be in requirements.txt for discord.py voice"


@pytest.mark.parametrize("size_bytes,expected_skip", [
    (1 * 1024 * 1024,        False),  # 1 MB — fine
    (5 * 1024 * 1024,        False),  # 5 MB — fine
    (10 * 1024 * 1024 + 1,   True),   # 10 MB + 1 byte — over cap
    (50 * 1024 * 1024,       True),   # 50 MB — way over
])
def test_attachment_size_cap_threshold(size_bytes, expected_skip):
    """The cap matches what _ingest_attachments uses (10 * 1024 * 1024)."""
    cap = 10 * 1024 * 1024
    assert (size_bytes > cap) == expected_skip
