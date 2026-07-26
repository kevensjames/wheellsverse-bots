"""Per-user spend ceiling actually bites: an over-cap user with no free local
model is REFUSED, not silently routed to paid openai. Streaming fails soft."""
import uuid
from unittest.mock import MagicMock

import pytest

from app.routers.nai import _sse_format
from app.services.router.router import Router, SpendCapExceeded
from app.services.router.types import Intent


class FakeAdapter:
    name = "fake"
    model = "m"


def _tracker(daily=False, monthly=False):
    t = MagicMock()
    t.over_daily_cap.return_value = daily
    t.over_monthly_cap.return_value = monthly
    return t


def test_over_daily_cap_no_local_refuses():
    r = Router(adapters={"openai": FakeAdapter()}, spend_tracker=_tracker(daily=True))
    with pytest.raises(SpendCapExceeded):
        r.select(intent=Intent.SIMPLE, user_id=uuid.uuid4())


def test_over_monthly_cap_also_enforced():
    r = Router(adapters={"openai": FakeAdapter()}, spend_tracker=_tracker(monthly=True))
    with pytest.raises(SpendCapExceeded) as ei:
        r.select(intent=Intent.SIMPLE, user_id=uuid.uuid4())
    assert ei.value.cap == "monthly"


def test_over_cap_routes_to_local_when_available():
    olla = FakeAdapter()
    r = Router(adapters={"openai": FakeAdapter(), "ollama": olla},
               spend_tracker=_tracker(daily=True))
    assert r.select(intent=Intent.SIMPLE, user_id=uuid.uuid4()) is olla  # free, no refusal


def test_under_cap_does_not_refuse():
    r = Router(adapters={"openai": FakeAdapter()}, spend_tracker=_tracker())
    assert r.select(intent=Intent.SIMPLE, user_id=uuid.uuid4()) is not None


def test_sse_format_emits_spend_cap_error_not_crash():
    def gen():
        raise SpendCapExceeded("daily")
        yield  # make it a generator

    out = b"".join(_sse_format(gen()))
    assert b"spend_cap" in out and b"usage limit" in out


def test_sse_format_delivers_tokens_then_clean_error():
    def gen():
        yield {"type": "token", "text": "hi"}
        raise RuntimeError("provider blew up mid-stream")

    out = b"".join(_sse_format(gen()))
    assert b"hi" in out                     # the token that made it through
    assert b"hit an error" in out           # a clean error event, not a raw 500
