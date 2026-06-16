"""Expert-agent presets — curated (system prompt + tool whitelist) bundles.

What this is NOT: a separate agent runtime. Every preset still runs through
KAI's existing Brain/Router/tool-loop. The preset just shapes the call:
  1. prepends a persona-specific system prompt
  2. filters the tool registry to a whitelist (so the SWE preset can't
     accidentally tweet, the Legal preset can't run trades, etc.)

Routes through the governance layer (@audited scope=presets.use_preset)
so every preset-driven chat call is recorded in audit.jsonl.
"""
from app.services.presets.registry import (
    PRESETS,
    PresetSpec,
    get_preset,
    list_presets,
)
from app.services.presets.filter import filter_registry

__all__ = [
    "PRESETS",
    "PresetSpec",
    "filter_registry",
    "get_preset",
    "list_presets",
]
