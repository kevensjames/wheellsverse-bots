# Local LLM Migration — Goodbye Anthropic/OpenAI Billing

**Goal:** Run wheellsverse_bots on local models (Ollama) instead of paying
Anthropic + OpenAI tokens. Fully reversible via a single env var.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Wrappers (`core/llm_client.py`, `core/claude_logged.py`) route to Ollama when `LLM_BACKEND=ollama` | **DONE** |
| 1 | `.env.example` documents new env vars | **DONE** |
| 2 | All non-tool LLM bypass files routed through wrappers (or backend-aware branches) | **DONE** |
| 3 | Better models pulled (`qwen2.5:7b`, `nomic-embed-text`) | **DONE** |
| 3 | `core/memory.py` embeddings switched to `nomic-embed-text` when local | **DONE** |
| 3 | Streaming paths (`core/narai_chat.py`, `core/zoom_clone.py`) routed to Ollama | **DONE** |
| 2.5 | `narai/bot.py` tool-calling agentic loop translated to qwen2.5 tools | **DONE** |
| ✓ | **All text-LLM paths run on Ollama with `LLM_BACKEND=ollama`** | **COMPLETE** |

## How to flip the switch

Add to `.env`:

```
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL_MAP={"gpt-4o":"qwen2.5:7b","gpt-4o-mini":"llama3.2:latest","claude-sonnet-4-6":"qwen2.5:7b","claude-haiku-4-5-20251001":"llama3.2:latest","claude-opus-4-7":"qwen2.5:7b","text-embedding-3-small":"nomic-embed-text"}
```

Unset `LLM_BACKEND` (or leave blank) to go back to cloud APIs. Both wrappers
check at call time, so flipping the env var doesn't require a restart of
anything except the bot processes themselves.

## What works today (Phase 1)

Every file that goes through the wrappers — **33 files** — instantly runs
on local models when `LLM_BACKEND=ollama`. Verified with:

```python
from core.claude_logged import create as claude_create
resp = claude_create(
    model="claude-sonnet-4-6", max_tokens=64,
    messages=[{"role": "user", "content": "Reply PONG"}],
    bot_name="smoke_test",
)
# resp.content[0].text == "PONG"   ← Ollama via shim
```

## What still hits cloud (Phase 2 — 20 files to refactor)

These bypass the wrappers and call `openai.OpenAI(...).chat.completions.create()`
or `anthropic.Anthropic(...).messages.create()` directly. They'll hit your
**cloud account** even when `LLM_BACKEND=ollama` until refactored.

### Real bypasses (need refactor)
- `setup_meta_tokens.py` (1)
- `bots/narai/narai/bot.py` (5)
- `bots/books/base_book_bot.py` (1)
- `core/memory.py` (2 — **embeddings**, needs `client.embeddings.create` path)
- `core/content_calendar.py` (1)
- `core/voice_router.py` (1)
- `core/decision_engine.py` (1)
- `core/monetization.py` (1)
- `core/dm_reply.py` (1)
- `core/cover_engine.py` (1)
- `core/threads.py` (4)
- `core/kdp_paperback.py` (1)
- `core/linkedin.py` (3)
- `core/elevenlabs.py` (1)
- `core/inbox/routes.py` (1)
- `core/kdp_uploader.py` (1)
- `narai/voice/stt.py` (1 — **audio**, see "non-text APIs" below)
- `second_brain_inbox/api/main.py` (1)
- `pipelines/content_pipeline.py` (1)
- `narai/marketing/marketing_autopilot.py` (1)

### Refactor recipe (90% of cases)

Find:
```python
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    max_tokens=1000,
)
text = resp.choices[0].message.content
```

Replace with:
```python
from core.llm_client import safe_openai_call
resp = safe_openai_call(
    messages=[...],
    model="gpt-4o",
    max_tokens=1000,
    bot_name="this_file",   # for spend attribution
)
text = resp.choices[0].message.content
```

For Anthropic call sites, use `from core.claude_logged import create as claude_create`.

## Non-text APIs (no Ollama equivalent — keep cloud or alternative)

These features don't have a local equivalent and will need a different
plan if you want zero cloud spend:

| Feature | Files | Local option |
|---|---|---|
| Embeddings | `core/memory.py` | `nomic-embed-text` via Ollama (pulled) |
| TTS (text-to-speech) | `core/elevenlabs.py` | ElevenLabs is a separate vendor — local: `kokoro-tts`, `piper` |
| STT (speech-to-text) | `narai/voice/stt.py` | `whisper.cpp` or Apple `MLX-Whisper` (free, runs on M4) |
| Image generation | `core/cover_engine.py`, `core/kdp_*.py` | Local: `ComfyUI` + SDXL/Flux on M4 |

## Hardware notes

- This Mac mini M4 has **16GB unified memory**
- `qwen2.5:7b` Q4_K_M ≈ 5GB on disk, ≈6GB RAM at runtime — fits comfortably
- Avoid 14B+ models — they'll swap to disk and crawl
- For higher quality without RAM upgrade: try `qwen2.5-coder:7b` for code, `deepseek-r1:7b` for reasoning

## Reversibility

Every change is gated on `LLM_BACKEND`. To roll back fully:
```
unset LLM_BACKEND     # or comment it out in .env
```
All wrapper-using callers immediately resume hitting OpenAI/Anthropic.
No code rollback needed.

## Cost model

Before: ~$daily Anthropic spend + ~$daily OpenAI spend (currently blocked).
After Phase 1: cloud spend drops to whatever the 20 bypass files generate.
After Phase 2: $0 cloud LLM spend. Electricity only.

A Mac mini M4 idle ≈ 4W, under inference load ≈ 20–40W. At $0.15/kWh
that's roughly **$0.005/hour** to run. Compared to ~$3/M input tokens
on Sonnet, you pay back the migration effort in days for any bot doing
real volume.
