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


def test_classify_simple_definitions():
    assert classify_intent("what is photosynthesis") == Intent.SIMPLE
    assert classify_intent("define epistemology") == Intent.SIMPLE
    assert classify_intent("what's a monad") == Intent.SIMPLE


def test_classify_simple_summaries_and_translations():
    assert classify_intent("summarize: the brown fox jumped") == Intent.SIMPLE
    assert classify_intent("tldr the apollo program") == Intent.SIMPLE
    assert classify_intent("translate hola to english") == Intent.SIMPLE


def test_simple_must_be_short():
    # Same opener but past the length cap stays GENERAL — we don't want
    # long context-heavy prompts going to the cheap 8B model.
    long_msg = "what is " + ("the meaning of life " * 30)
    assert len(long_msg) > 200
    assert classify_intent(long_msg) == Intent.GENERAL


def test_code_beats_simple():
    # "what is" matches simple, but code signal must win — debugging a
    # function isn't an 8B-model task.
    assert classify_intent("what is wrong with this python function") == Intent.CODE


def test_realtime_beats_simple():
    # "what's" is a simple opener but "latest news" needs fresh web data.
    assert classify_intent("what's the latest news on AI") == Intent.REALTIME


def test_general_when_no_simple_keyword():
    # Short, no simple opener → GENERAL, not SIMPLE. The classifier is
    # deliberately conservative: prefer GPT-4o-mini to Llama-8B unless
    # we're confident the task is trivial.
    assert classify_intent("tell me a poem") == Intent.GENERAL
