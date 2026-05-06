"""Tests for response tier classifier."""
from infra.brain.tiers import classify


def test_short_greeting_is_fast():
    assert classify("hey") == "fast"
    assert classify("hi nar") == "fast"


def test_analysis_is_deep():
    assert classify("analyze the current market conditions for NVDA") == "deep"
    assert classify("explain how the LSTM model works") == "deep"


def test_long_prompt_is_deep():
    long = "tell me " * 50
    assert classify(long) == "deep"


def test_quick_query_is_fast():
    assert classify("what is the price of BTC") == "fast"


def test_write_is_deep():
    assert classify("write a blog post about AI trading strategies") == "deep"
