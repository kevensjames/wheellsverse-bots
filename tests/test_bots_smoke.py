"""Smoke-test every bot under bots/ to catch import errors and interface drift.

Each bot is loaded by file path (not full package import) so the test runs
without depending on the rest of the bot tree being importable. The test does
NOT instantiate the bot — BaseBot.__init__ writes registry/log files.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOTS_DIR = ROOT / "bots"

SKIP_DIRS = {"narai", "_archive", "__pycache__"}


def _discover_bots() -> list[Path]:
    """Find every bot.py under bots/, skipping known non-bot dirs."""
    found: list[Path] = []
    for p in BOTS_DIR.rglob("bot.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        found.append(p)
    return sorted(found)


def _load_module_from_path(path: Path):
    """Load a Python file as a uniquely-named module without importing siblings."""
    mod_name = "_smoke_" + "_".join(path.relative_to(ROOT).with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOT_PATHS = _discover_bots()


@pytest.mark.parametrize("bot_path", BOT_PATHS, ids=lambda p: str(p.relative_to(ROOT)))
def test_bot_imports_and_has_run(bot_path: Path) -> None:
    from core.base_bot import BaseBot

    module = _load_module_from_path(bot_path)

    bot_classes = [
        cls for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls is not BaseBot
        and issubclass(cls, BaseBot)
        and cls.__module__ == module.__name__
    ]

    assert bot_classes, f"{bot_path.relative_to(ROOT)} defines no BaseBot subclass"

    for cls in bot_classes:
        run = getattr(cls, "run", None)
        assert run is not None, f"{cls.__name__} has no run() method"
        assert callable(run), f"{cls.__name__}.run is not callable"


def test_at_least_100_bots_discovered() -> None:
    """Guard against accidental directory rename collapsing the suite."""
    assert len(BOT_PATHS) >= 100, f"expected 100+ bots, found {len(BOT_PATHS)}"
