"""Tests for the RAG pipeline (real ChromaDB ingest + query).

These exercise the actual chunk → embed → upsert → query → score path,
so the ``real_chroma`` marker opts out of the conftest's chroma-mocking
fixture and gives the suite an isolated, on-disk per-test Chroma instance.
"""
import json
import pytest

# All tests in this file need real ChromaDB.
pytestmark = pytest.mark.real_chroma


def test_ingest_text_and_query():
    from infra.brain.rag import ingest_text, query

    text = "NarAI uses an LSTM model to forecast stock prices based on historical data."
    chunks = ingest_text(text, source_label="test_doc")
    assert chunks >= 1

    results = query("LSTM stock price forecasting")
    assert len(results) >= 1
    assert results[0]["source"] == "test_doc"
    assert results[0]["score"] > 0


def test_ingest_markdown_file(tmp_path):
    from infra.brain.rag import ingest, query

    md = tmp_path / "notes.md"
    md.write_text("# Trading Strategy\nRSI below 30 indicates oversold conditions.")

    chunks = ingest(str(md), source_label="notes.md")
    assert chunks >= 1

    results = query("RSI oversold indicator")
    assert len(results) >= 1


def test_ingest_csv_file(tmp_path):
    from infra.brain.rag import ingest, query

    csv_file = tmp_path / "trades.csv"
    csv_file.write_text("ticker,action,price\nBTC,BUY,45000\nETH,SELL,3200\n")

    ingest(str(csv_file), source_label="trades.csv")
    results = query("BTC buy trade")
    assert len(results) >= 1


def test_ingest_json_file(tmp_path):
    from infra.brain.rag import ingest

    data = [{"key": "insight_1", "content": "Market is bullish in Q1 2026"}]
    jf = tmp_path / "data.json"
    jf.write_text(json.dumps(data))
    chunks = ingest(str(jf), source_label="data.json")
    assert chunks >= 1


def test_delete_source():
    from infra.brain.rag import _get_rag_collection, delete_source, ingest_text, query

    ingest_text("Some text about crypto markets", source_label="to_delete")
    delete_source("to_delete")
    assert _get_rag_collection().count() == 0


def test_query_context_format():
    from infra.brain.rag import ingest_text, query_context

    ingest_text("Ethereum 2.0 uses proof of stake for consensus", source_label="eth_notes")
    ctx = query_context("ethereum consensus")
    assert "[RAG CONTEXT]" in ctx
    assert "eth_notes" in ctx
