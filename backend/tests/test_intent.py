from app.services.router.intent import classify_intent
from app.services.router.types import Intent


def test_classify_code():
    assert classify_intent("debug this python function") == Intent.CODE
    assert classify_intent("write a regex for emails") == Intent.CODE
    assert classify_intent("```\nprint('hi')\n```") == Intent.CODE


def test_classify_realtime():
    assert classify_intent("what's the latest news on tariffs") == Intent.REALTIME
    assert classify_intent("price of AAPL right now") == Intent.REALTIME
    assert classify_intent("who is the current ceo of openai") == Intent.REALTIME


def test_classify_general_default():
    assert classify_intent("tell me a story") == Intent.GENERAL
    assert classify_intent("how do volcanoes work") == Intent.GENERAL


def test_code_beats_realtime():
    # "current" matches both, but code signal wins because it's checked first
    assert classify_intent("debug my current python script") == Intent.CODE
