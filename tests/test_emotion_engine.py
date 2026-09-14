"""
tests/test_emotion_engine.py — unit tests for core/emotion_engine.py

The engine stores mood history in SQLite (DB_PATH) and a psych profile JSON
(PROFILE_PATH). Both are patched to temp files and API keys are removed so
detect_mood exercises the local keyword classifier (no network calls).
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

from core import emotion_engine
from core.emotion_engine import MOODS, EmotionEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(emotion_engine, "DB_PATH", tmp_path / "mood.db")
    monkeypatch.setattr(emotion_engine, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return EmotionEngine()


# ── detect_mood (keyword classifier) ──────────────────────────────────────────

def test_detect_empty_text(engine):
    r = engine.detect_mood("")
    assert r["mood"] == "neutral"
    assert r["method"] == "empty"


def test_detect_sad(engine):
    r = engine.detect_mood("I feel so sad and lonely, everything hurts and I'm exhausted")
    assert r["mood"] == "sad"
    assert r["confidence"] == "high"   # 3+ keyword hits
    assert r["method"] == "keywords"


def test_detect_happy(engine):
    r = engine.detect_mood("I'm so happy and excited, this is amazing and wonderful!")
    assert r["mood"] == "happy"
    assert r["confidence"] == "high"


def test_detect_angry(engine):
    r = engine.detect_mood("I am furious and angry, this is so unfair, I'm fed up")
    assert r["mood"] == "angry"


def test_detect_anxious(engine):
    r = engine.detect_mood("I feel anxious and worried, so much stress and pressure, I'm scared")
    assert r["mood"] == "anxious"


def test_detect_neutral_without_keywords(engine):
    r = engine.detect_mood("The meeting is scheduled for 3pm on the calendar")
    assert r["mood"] == "neutral"
    assert r["confidence"] == "low"


def test_detect_weak_signal_stays_low_without_ai(engine):
    # single sad keyword, no API keys -> keyword result with low confidence
    r = engine.detect_mood("I am a bit tired")
    assert r["method"] == "keywords"
    assert r["confidence"] == "low"


# ── store / retrieve ──────────────────────────────────────────────────────────

def test_get_current_mood_default_neutral(engine):
    assert engine.get_current_mood() == "neutral"


def test_store_and_get_current_mood(engine):
    engine.store_mood("happy", 0.8, source="whatsapp", raw_text="great day")
    assert engine.get_current_mood() == "happy"


def test_detect_and_store(engine):
    r = engine.detect_and_store("I'm so happy and excited and grateful and blessed")
    assert r["mood"] == "happy"
    assert engine.get_current_mood() == "happy"
    assert len(engine.get_mood_history()) == 1


def test_mood_history_respects_window(engine):
    engine.store_mood("happy")
    # inject an old row directly, outside the 24h window
    old_ts = (datetime.now() - timedelta(hours=48)).isoformat()
    conn = sqlite3.connect(str(emotion_engine.DB_PATH))
    conn.execute(
        "INSERT INTO mood_log (ts, mood, score, source) VALUES (?,?,?,?)",
        (old_ts, "sad", 0.0, "text"),
    )
    conn.commit()
    conn.close()
    recent = engine.get_mood_history(hours=24)
    assert [r["mood"] for r in recent] == ["happy"]
    wide = engine.get_mood_history(hours=72)
    assert {r["mood"] for r in wide} == {"happy", "sad"}


# ── mood trend ────────────────────────────────────────────────────────────────

def test_mood_trend_no_data(engine):
    t = engine.get_mood_trend()
    assert t["dominant"] == "neutral"
    assert t["trend"] == "stable"
    assert "Not enough data" in t["insights"]


def test_mood_trend_dominant_and_counts(engine):
    for _ in range(3):
        engine.store_mood("sad")
    engine.store_mood("happy")
    t = engine.get_mood_trend(days=7)
    assert t["dominant"] == "sad"
    assert t["counts"]["sad"] == 3
    assert t["total_readings"] == 4


def test_mood_trend_declining_direction(engine):
    # older readings happy, recent readings sad -> declining
    def _insert(mood, ts):
        conn = sqlite3.connect(str(emotion_engine.DB_PATH))
        conn.execute(
            "INSERT INTO mood_log (ts, mood, score, source) VALUES (?,?,?,?)",
            (ts, mood, 0.0, "text"),
        )
        conn.commit()
        conn.close()

    base = datetime.now()
    for i in range(3):  # older -> happy
        _insert("happy", (base - timedelta(hours=10 + i)).isoformat())
    for i in range(3):  # recent -> sad
        _insert("sad", (base - timedelta(minutes=i)).isoformat())
    t = engine.get_mood_trend(days=7)
    assert t["trend"] == "declining"


# ── content style / prompt ────────────────────────────────────────────────────

def test_content_style_defaults_to_current_mood(engine):
    engine.store_mood("sad")
    style = engine.get_content_style()
    assert style["mood"] == "sad"
    assert style["emoji"] == MOODS["sad"]["emoji"]
    assert style["blog_tone"] == MOODS["sad"]["content_style"]["blog_tone"]


def test_content_style_unknown_mood_falls_back_to_neutral(engine):
    style = engine.get_content_style(mood="ecstatic")
    assert style["mood"] == "ecstatic"
    assert style["blog_tone"] == MOODS["neutral"]["content_style"]["blog_tone"]


def test_system_prompt_injection_contains_mood(engine):
    text = engine.get_mood_system_prompt_injection(mood="angry")
    assert "ANGRY" in text
    assert MOODS["angry"]["narai_tone"] in text


# ── profile + insights ────────────────────────────────────────────────────────

def test_profile_tracks_counts_and_streaks(engine):
    engine.store_mood("sad")
    engine.store_mood("sad")
    profile = engine.get_profile()
    assert profile["total_readings"] == 2
    assert profile["mood_counts"]["sad"] == 2
    assert profile["consecutive_sad_days"] == 2
    assert profile["consecutive_happy_days"] == 0


def test_happy_resets_sad_streak(engine):
    engine.store_mood("sad")
    engine.store_mood("happy")
    profile = engine.get_profile()
    assert profile["consecutive_sad_days"] == 0
    assert profile["consecutive_happy_days"] == 1


def test_insights_warn_on_consecutive_sad(engine):
    for _ in range(3):
        engine.store_mood("sad")
    insights = engine.get_personalized_insights()
    assert any("heavy" in i.lower() for i in insights)


def test_insights_acknowledge_happy_streak(engine):
    for _ in range(3):
        engine.store_mood("happy")
    insights = engine.get_personalized_insights()
    assert any("good place" in i.lower() for i in insights)


def test_checkin_message_is_from_mood_set(engine):
    engine.store_mood("sad")
    msg = engine.get_checkin_message(mood="sad")
    assert isinstance(msg, str) and msg


def test_empathetic_response_fallback_without_api(engine):
    # no API keys -> falls back to the mood's canned narai_voice
    resp = engine.get_empathetic_response("I'm so sad and lonely", mood="sad")
    assert resp == MOODS["sad"]["narai_voice"]


# ── profile persistence ───────────────────────────────────────────────────────

def test_profile_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(emotion_engine, "DB_PATH", tmp_path / "mood.db")
    monkeypatch.setattr(emotion_engine, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    e1 = EmotionEngine()
    e1.store_mood("happy")
    e2 = EmotionEngine()
    assert e2.get_profile()["mood_counts"]["happy"] == 1


# ── module-level singleton helpers ────────────────────────────────────────────

def test_module_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(emotion_engine, "DB_PATH", tmp_path / "mood.db")
    monkeypatch.setattr(emotion_engine, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(emotion_engine, "_engine", None)
    r = emotion_engine.detect_mood("I'm angry, furious and fed up with this")
    assert r["mood"] == "angry"
    style = emotion_engine.get_content_style("happy")
    assert style["mood"] == "happy"
    assert isinstance(emotion_engine.get_mood_prompt("neutral"), str)
