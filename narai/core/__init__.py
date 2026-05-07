"""NarAI core layer — identity, overwhelm, mode, storage, db, patterns, ...

The canonical AI brain lives in ``infra.brain`` and is accessed exclusively
via ``infra.brain.interface.BrainClient``. This package no longer re-exports
brain symbols (``MemoryStore``, ``Fact``, ``Episode``); construct them via a
``BrainClient`` instead.

Heavy optional deps (chromadb, etc.) are imported lazily so subpackages like
shopify_mt can be loaded without them installed.
"""
from .identity import Identity, Mode, build_system_prompt

try:
    from .extractor import extract_facts
except ImportError:
    pass  # heavy deps absent — shopify_mt and lightweight paths still work

try:
    from .overwhelm import (
        detect, detect_async, OverwhelmState,
        modifier_for as overwhelm_modifier_for,
    )
    from .mode_router import (
        route, route_async, ModeDecision, parse_override,
        modifier_for as mode_modifier_for,
    )
except ImportError:
    pass

__all__ = [
    "Identity", "Mode", "build_system_prompt",
    "extract_facts",
    "detect", "detect_async", "OverwhelmState", "overwhelm_modifier_for",
    "route", "route_async", "ModeDecision", "parse_override", "mode_modifier_for",
]
