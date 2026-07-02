from core.portfolio import llm


def test_default_generate_returns_text(monkeypatch):
    import core.base_bot as bb

    class MockBot:
        def claude(self, prompt, **kw):
            return "GENERATED:" + prompt[:10]

    monkeypatch.setattr(bb, "BaseBot", lambda name, category: MockBot())
    out = llm.default_generate("hello world prompt")
    assert out.startswith("GENERATED:")


def test_default_generate_fail_soft(monkeypatch):
    import core.base_bot as bb

    class MockBot:
        def claude(self, prompt, **kw):
            raise RuntimeError("llm down")

    monkeypatch.setattr(bb, "BaseBot", lambda name, category: MockBot())
    assert llm.default_generate("x") == ""
