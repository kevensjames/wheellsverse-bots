# tests/test_portfolio_flags.py
from core.portfolio import state


def test_flag_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert state.get_flag("n8n", "warmup_complete") is False        # default
    state.set_flag("n8n", "warmup_complete", True)
    assert state.get_flag("n8n", "warmup_complete") is True          # persisted (re-read)
    # flags don't disturb the rest of state
    assert state.load_state("n8n")["phase"] == "planning"


def test_send_counter(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert state.send_count("n8n", "2026-06-23") == 0               # default
    state.record_send("n8n", "2026-06-23", 3)
    state.record_send("n8n", "2026-06-23")                          # +1
    assert state.send_count("n8n", "2026-06-23") == 4
    assert state.send_count("n8n", "2026-06-24") == 0              # per-day
