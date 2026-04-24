from narai.voice.formatter import (
    strip_markdown, truncate_for_voice, to_ssml, format_for_voice,
)


def test_strip_code_blocks():
    t = "Here is code:\n```python\nprint('hi')\n```\nDone."
    out = strip_markdown(t)
    assert "```" not in out
    assert "[code block shown in chat]" in out


def test_strip_bold_italic():
    out = strip_markdown("This is **bold** and *italic*.")
    assert "**" not in out
    assert "bold" in out and "italic" in out


def test_strip_bullets():
    out = strip_markdown("- first\n- second\n- third")
    assert "-" not in out


def test_truncate_companion_shorter():
    long = ". ".join([f"Sentence {i}" for i in range(20)]) + "."
    out = truncate_for_voice(long, "companion")
    # companion capped at 3 sentences
    assert out.count(".") <= 4


def test_truncate_operator_allows_more():
    long = ". ".join([f"Sentence {i}" for i in range(20)]) + "."
    op = truncate_for_voice(long, "operator")
    comp = truncate_for_voice(long, "companion")
    assert len(op) > len(comp)


def test_ssml_companion_slower():
    ssml = to_ssml("Hello there.", "companion")
    assert 'rate="95%"' in ssml
    assert "<speak>" in ssml


def test_ssml_operator_normal():
    ssml = to_ssml("Hello there.", "operator")
    assert 'rate="100%"' in ssml


def test_format_for_voice_returns_both():
    spoken, chat = format_for_voice("**Bold** reply.", mode="operator")
    assert "**" not in spoken
    assert "**Bold**" in chat  # chat display keeps markdown
