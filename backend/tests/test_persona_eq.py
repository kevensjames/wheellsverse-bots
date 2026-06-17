"""KAI persona + emotional-intelligence — unit tests (isolated temp DBs)."""
import pytest

from app.services.persona import storage as pstore
from app.services.persona import composer as pcomposer
from app.services.persona.injection import persona_preamble
from app.services.eq import storage as eqstore
from app.services.eq.detection import detect_mood
from app.services.eq.adaptation import directive_for
from app.services.eq.injection import analyze as eq_analyze
from app.services.nai_brain.system_prompt import build_system_prompt


@pytest.fixture(autouse=True)
def _temp_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(pstore, "PERSONA_DB_PATH", tmp_path / "persona.db")
    monkeypatch.setattr(eqstore, "EQ_DB_PATH", tmp_path / "eq.db")
    # scopes default OFF; tests opt in
    for v in ("KAI_SCOPE_PERSONA", "KAI_SCOPE_EQ"):
        monkeypatch.delenv(v, raising=False)
    yield


# ─── persona storage + seeding ─────────────────────────────────────────
def test_seed_defaults_is_idempotent():
    n1 = pstore.seed_defaults()
    assert n1 == len(pstore._DEFAULT_PERSONA) > 0
    n2 = pstore.seed_defaults()           # second call must not duplicate
    assert n2 == 0
    assert pstore.count_entries() == n1


def test_add_and_list_and_archive():
    e = pstore.add_entry("humor", "loves a good pun", source="operator")
    assert e.status == "active"
    assert any(x.text == "loves a good pun" for x in pstore.list_entries(status="active"))
    pstore.set_entry_status(e.id, "archived")
    assert all(x.id != e.id for x in pstore.list_entries(status="active"))


def test_bad_section_rejected():
    with pytest.raises(ValueError):
        pstore.add_entry("not_a_section", "x")


def test_composer_groups_by_section():
    pstore.add_entry("identity", "KAI, Jhon's partner")
    pstore.add_entry("voice", "warm + direct")
    text = pcomposer.compose_persona(pstore.list_entries(status="active"))
    assert "[identity]" in text and "[voice]" in text and "warm + direct" in text


# ─── persona injection (scope-gated) ───────────────────────────────────
def test_persona_injection_off_when_scope_disabled(monkeypatch):
    pstore.seed_defaults()
    assert persona_preamble() == ""          # KAI_SCOPE_PERSONA unset


def test_persona_injection_on_when_scoped(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_PERSONA", "1")
    pstore.seed_defaults()
    out = persona_preamble()
    assert out.startswith("WHO YOU ARE")
    assert "companion" in out.lower()


# ─── mood detection ────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("I'm so stressed, too much to do and no time", "stressed"),
    ("ugh this is still broken, so frustrated", "frustrated"),
    ("I'm really worried, what if it fails", "anxious"),
    ("feeling exhausted and burned out", "tired"),
    ("this is amazing, can't wait, let's go!", "excited"),
    ("let's build this, locked in and focused", "motivated"),
    ("the invoice total is 200 dollars", "neutral"),
])
def test_detect_mood(text, expected):
    mood, conf = detect_mood(text)
    assert mood == expected
    if expected == "neutral":
        assert conf == 0.0
    else:
        assert 0.0 < conf <= 1.0


def test_detect_mood_empty():
    assert detect_mood("") == ("neutral", 0.0)


def test_directive_present_for_moods_blank_for_neutral():
    assert directive_for("frustrated")
    assert directive_for("neutral") == ""


# ─── eq injection (scope-gated) + storage ──────────────────────────────
def test_eq_analyze_off_when_scope_disabled():
    mood, conf, pre = eq_analyze("I'm so frustrated this is broken")
    assert mood == "neutral" and conf == 0.0 and pre == ""


def test_eq_analyze_on_returns_directive(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_EQ", "1")
    mood, conf, pre = eq_analyze("ugh so frustrated, this still doesn't work")
    assert mood == "frustrated" and conf > 0
    assert "EMOTIONAL CONTEXT" in pre and "frustrated" in pre.lower()


def test_eq_storage_record_and_stats():
    eqstore.record_mood("stressed", 0.8, "too much to do")
    eqstore.record_mood("stressed", 0.5, "swamped")
    eqstore.record_mood("happy", 0.6, "great day")
    s = eqstore.stats()
    assert s["total_samples"] == 3
    assert s["by_mood"]["stressed"] == 2
    assert s["latest_mood"] == "happy"          # most recent
    assert len(eqstore.recent(limit=2)) == 2


# ─── system prompt composition ─────────────────────────────────────────
def test_build_system_prompt_layers_persona_and_eq(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_PERSONA", "1")
    monkeypatch.setenv("KAI_SCOPE_EQ", "1")
    pstore.seed_defaults()
    _, _, eq_pre = eq_analyze("so frustrated, broken again")
    prompt = build_system_prompt("", eq_preamble=eq_pre)
    assert "WHO YOU ARE" in prompt                 # persona first
    assert "EMOTIONAL CONTEXT" in prompt           # eq directive
    assert prompt.index("WHO YOU ARE") < prompt.index("EMOTIONAL CONTEXT")  # ordering
    assert "You are KAI" in prompt                 # baseline still present


def test_build_system_prompt_plain_when_scopes_off():
    prompt = build_system_prompt("")
    assert "WHO YOU ARE" not in prompt and "EMOTIONAL CONTEXT" not in prompt
    assert "You are KAI" in prompt                 # baseline always present
