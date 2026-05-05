import tempfile
from narai.core.memory import MemoryStore
from narai.core.identity import build_system_prompt


def _store():
    tmp = tempfile.mkdtemp()
    return MemoryStore(data_dir=tmp)


def test_remember_and_recall_fact():
    m = _store()
    m.remember_fact("jhon", "Wants to run own company", category="goal")
    facts = m.recall_facts("jhon")
    assert len(facts) == 1
    assert facts[0].category == "goal"


def test_recall_by_category():
    m = _store()
    m.remember_fact("jhon", "Build NarAI v2", category="goal")
    m.remember_fact("jhon", "Direct tone", category="preference")
    goals = m.recall_facts("jhon", category="goal")
    prefs = m.recall_facts("jhon", category="preference")
    assert len(goals) == 1 and len(prefs) == 1
    assert goals[0].content == "Build NarAI v2"


def test_user_isolation():
    m = _store()
    m.remember_fact("jhon", "X", category="goal")
    m.remember_fact("alice", "Y", category="goal")
    assert len(m.recall_facts("jhon")) == 1
    assert len(m.recall_facts("alice")) == 1


def test_episode_semantic_recall():
    m = _store()
    m.log_episode("jhon", "User felt overwhelmed by Nexora deployment")
    m.log_episode("jhon", "User shipped the Shopify publisher module")
    m.log_episode("jhon", "User bought groceries")
    eps = m.recall_episodes("jhon", "stress about launching", k=2)
    assert len(eps) >= 1
    assert any("overwhelm" in e.content.lower() for e in eps)


def test_get_context_formats_cleanly():
    m = _store()
    m.remember_fact("jhon", "Run own company", category="goal")
    m.remember_fact("jhon", "J.K. Blaze", category="identity")
    ctx = m.get_context("jhon")
    assert "Known about this user" in ctx
    assert "Goal:" in ctx
    assert "Identity:" in ctx
    # identity listed before goal (priority order)
    assert ctx.index("Identity:") < ctx.index("Goal:")


def test_integration_with_system_prompt():
    m = _store()
    m.remember_fact("jhon", "Ship NarAI v2 this week", category="goal")
    ctx = m.get_context("jhon")
    prompt = build_system_prompt(user_context=ctx)
    assert "NarAI v2" in prompt
    assert "NarAI" in prompt  # identity block still present


def test_empty_context_returns_empty_string():
    m = _store()
    assert m.get_context("nobody") == ""


def test_extract_facts_parses_json():
    from narai.core.extractor import extract_facts

    def fake_llm(system, user):
        return '[{"category": "goal", "content": "ship Nexora"}]'

    out = extract_facts("I want to ship Nexora next month", fake_llm)
    assert len(out) == 1
    assert out[0]["category"] == "goal"


def test_extract_facts_handles_garbage():
    from narai.core.extractor import extract_facts
    out = extract_facts("hello", lambda s, u: "not json at all")
    assert out == []
