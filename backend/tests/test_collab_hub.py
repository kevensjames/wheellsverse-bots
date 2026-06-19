import pytest
from app.services.collab.hub import Hub


class FakeConn:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_json(self, obj):
        if self.fail:
            raise RuntimeError("dead socket")
        self.sent.append(obj)


def test_join_presence_leave():
    h = Hub()
    a, b = FakeConn(), FakeConn()
    h.join("room1", "a", a, {"name": "Jhon"})
    h.join("room1", "b", b, {"name": "Guest"})
    assert h.count("room1") == 2
    names = [p["name"] for p in h.presence("room1")]
    assert names == ["Jhon", "Guest"]
    assert h.presence("room1")[0]["id"] == "a"
    h.leave("room1", "a")
    assert h.count("room1") == 1
    assert [p["name"] for p in h.presence("room1")] == ["Guest"]


def test_empty_room_is_removed():
    h = Hub()
    h.join("r", "a", FakeConn())
    h.leave("r", "a")
    assert "r" not in h.rooms()


@pytest.mark.asyncio
async def test_broadcast_reaches_all_and_excludes():
    h = Hub()
    a, b, c = FakeConn(), FakeConn(), FakeConn()
    for cid, conn in (("a", a), ("b", b), ("c", c)):
        h.join("room", cid, conn, {"name": cid})
    sent = await h.broadcast("room", {"type": "msg", "text": "hi"}, exclude="a")
    assert sent == 2
    assert a.sent == []                         # excluded
    assert b.sent == [{"type": "msg", "text": "hi"}]
    assert c.sent == [{"type": "msg", "text": "hi"}]


@pytest.mark.asyncio
async def test_broadcast_drops_dead_connections():
    h = Hub()
    good, bad = FakeConn(), FakeConn(fail=True)
    h.join("room", "good", good)
    h.join("room", "bad", bad)
    sent = await h.broadcast("room", {"type": "ping"})
    assert sent == 1                            # only the good one
    assert h.count("room") == 1                 # dead one auto-removed
    assert "bad" not in [p["id"] for p in h.presence("room")]
