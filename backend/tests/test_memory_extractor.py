"""KAI v1 build #3 — background memory extractor (continual learning)."""
import uuid

from app.services.memory import extractor


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRouter:
    def __init__(self, content):
        self._content = content

    def complete(self, **kwargs):
        return _FakeResult(self._content)


class _Hit:
    def __init__(self, sim):
        self.similarity = sim
        self.content = "existing"
        self.score = sim


def test_extract_and_store_dedupes_and_stores(monkeypatch):
    uid = uuid.uuid4()
    facts = ('[{"content":"Lives in Taunton, MA","type":"fact"},'
             '{"content":"Prefers concise replies","type":"preference"}]')
    added: list = []

    def fake_search(session, *, user_id, query, k=1, memory_type=None, bump_last_used=True):
        return [_Hit(0.95)] if "Taunton" in query else [_Hit(0.4)]  # first is a near-dup

    def fake_add(session, *, user_id, content, memory_type="note", metadata=None):
        added.append((content, memory_type))

    monkeypatch.setattr(extractor, "search_memories", fake_search)
    monkeypatch.setattr(extractor, "add_memory", fake_add)

    out = extractor.extract_and_store(
        user_id=uid, messages=[{"role": "user", "content": "hi"}],
        router=_FakeRouter(facts), session=object(),  # non-None → no commit/close
    )
    assert out["extracted"] == 2
    assert out["stored"] == 1 and out["skipped_dupe"] == 1
    assert added == [("Prefers concise replies", "preference")]  # dup skipped, new stored


def test_parse_facts_tolerates_fences_and_garbage():
    assert extractor._parse_facts("[]") == []
    assert extractor._parse_facts("no json here") == []
    fenced = "```json\n[{\"content\":\"A\",\"type\":\"fact\"}]\n```"
    assert extractor._parse_facts(fenced) == [{"content": "A", "type": "fact"}]


def test_extract_is_failsoft_on_router_error(monkeypatch):
    class _Boom:
        def complete(self, **kwargs):
            raise RuntimeError("provider down")

    out = extractor.extract_and_store(
        user_id=uuid.uuid4(), messages=[{"role": "user", "content": "hi"}],
        router=_Boom(), session=object(),
    )
    assert out == {"extracted": 0, "stored": 0, "skipped_dupe": 0}
