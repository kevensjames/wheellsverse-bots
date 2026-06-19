import uuid
import pytest
from unittest.mock import MagicMock
from app.services.ceo import store as st
from app.services.tools.ceo_query import CeoQueryTool
from app.services.tools.base import ToolContext, ToolError


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    yield


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_board_action_reports_company():
    st.upsert_company("Grow net revenue")
    out = CeoQueryTool().execute(_ctx(), action="board")
    assert out["company"]["goal"] == "Grow net revenue"


def test_decisions_action():
    st.record_decision("reprioritize", "pause cold email")
    out = CeoQueryTool().execute(_ctx(), action="decisions")
    assert out["decisions"][0]["kind"] == "reprioritize"


def test_bad_action_raises():
    with pytest.raises(ToolError):
        CeoQueryTool().execute(_ctx(), action="nonsense")
