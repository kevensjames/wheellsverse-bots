from narai.core.identity import Identity, build_system_prompt


def test_identity_defaults():
    i = Identity()
    assert i.name == "NarAI"
    assert len(i.behavior_rules) >= 5
    assert len(i.forbidden_behaviors) >= 3


def test_prompt_contains_core_elements():
    prompt = build_system_prompt()
    assert "NarAI" in prompt
    assert "execution" in prompt.lower()
    assert "one question at a time" in prompt.lower()
    # forbidden behavior is declared explicitly
    assert "great question" in prompt.lower()


def test_prompt_with_mode():
    prompt = build_system_prompt(mode="operator")
    assert "operator" in prompt.lower()


def test_prompt_with_user_context():
    ctx = "Goal: ship NarAI v2 this week."
    prompt = build_system_prompt(user_context=ctx)
    assert "ship NarAI v2" in prompt


def test_prompt_is_readable_not_a_wall():
    prompt = build_system_prompt()
    assert prompt.count("\n") < 80
    assert "Rules you always follow:" in prompt
    assert "Things you never do:" in prompt
