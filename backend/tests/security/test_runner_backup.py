from datetime import datetime, timezone
from pathlib import Path

from app.services.security.runners.backup import parse_snapshots

FIX = Path(__file__).parent / "fixtures"


def test_parse_snapshots_counts_and_age():
    now = datetime(2026, 6, 18, 1, 0, 0, tzinfo=timezone.utc).timestamp()  # 1h after newest
    count, age = parse_snapshots((FIX / "restic_snapshots.json").read_text(), now)
    assert count == 2
    assert 3500 < age < 3700  # ~3600s


def test_parse_snapshots_empty():
    assert parse_snapshots("[]", 0.0) == (0, None)
    assert parse_snapshots("", 0.0) == (0, None)
