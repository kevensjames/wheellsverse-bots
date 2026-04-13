#!/usr/bin/env python3
"""
core/base_bot.py
─────────────────────────────────────────────────────────────────────────────
Base class for all WheellsVerse bots.
Every bot inherits from BaseBot and overrides run().
Supports both OpenAI and Anthropic (Claude) AI backends.
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import os
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

# Load root .env
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# ─── Token usage log ─────────────────────────────────────────────────────────

_TOKEN_LOG = ROOT / "data" / "token_usage.json"


def _log_token_usage(provider: str, model: str, prompt_tokens: int,
                     completion_tokens: int, bot_name: str) -> None:
    """Append a token usage record to the centralized log."""
    try:
        _TOKEN_LOG.parent.mkdir(parents=True, exist_ok=True)
        records = []
        if _TOKEN_LOG.exists():
            try:
                records = json.loads(_TOKEN_LOG.read_text())
            except Exception:
                records = []
        records.append({
            "ts": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "bot": bot_name,
        })
        # Keep last 5000 records to avoid unbounded growth
        if len(records) > 5000:
            records = records[-5000:]
        _TOKEN_LOG.write_text(json.dumps(records, indent=2))
    except Exception:
        pass  # Token logging is best-effort


def _retry(fn, retries: int = 3, delay: float = 2.0, logger=None):
    """Retry a callable up to `retries` times with exponential backoff."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt < retries - 1:
                wait = delay * (attempt + 1)
                if logger:
                    logger.warning(f"Retry {attempt + 1}/{retries} after {wait}s: {e}")
                time.sleep(wait)
            else:
                raise


class BaseBot(ABC):
    """
    Abstract base class for every bot in the WheellsVerse ecosystem.
    Provides: logging, OpenAI + Claude clients, config loading, output saving,
    error handling, timing, and status reporting.
    """

    def __init__(self, name: str, category: str, config_path: Optional[Path] = None):
        self.name = name
        self.category = category
        self.start_time: Optional[float] = None
        self.status = "idle"          # idle | running | done | error
        self.last_run: Optional[datetime] = None
        self.run_count = 0

        # Paths
        self.root_dir = ROOT
        self.output_dir = ROOT / "outputs" / category / name
        self.log_dir = ROOT / "logs"
        self.data_dir = ROOT / "data"

        # Create dirs
        for d in [self.output_dir, self.log_dir, self.data_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Config
        if config_path is None:
            config_path = Path(__file__).parent.parent / "bots" / category / name / "config.json"
        self.config = self._load_config(config_path)

        # Logger
        self.logger = self._setup_logger()

        # AI clients (lazy — only loaded when needed)
        self._client = None
        self._claude_client = None

        self.logger.info(f"🤖 {self.name} initialized")

    # ─── Config ────────────────────────────────────────────────────────────────

    def _load_config(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    # ─── Logger ────────────────────────────────────────────────────────────────

    def _setup_logger(self) -> logging.Logger:
        log_file = self.log_dir / f"{self.name}.log"
        logger = logging.getLogger(self.name)
        if not logger.handlers:
            level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
            logger.setLevel(level)
            fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s — %(message)s",
                                    datefmt="%Y-%m-%d %H:%M:%S")
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            logger.addHandler(fh)
            logger.addHandler(sh)
        return logger

    # ─── OpenAI Client ─────────────────────────────────────────────────────────

    @property
    def client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY not set in .env")
                self._client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError("openai package not installed. Run: pip install openai")
        return self._client

    def _ai_claude(self, prompt: str, system: str = None,
                   model: str = None, max_tokens: int = 2000,
                   temperature: float = 0.7) -> str:
        """Call Claude (Anthropic) directly — used as fallback when OpenAI quota is exceeded."""
        import anthropic
        claude_model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        msgs = [{"role": "user", "content": prompt}]
        kwargs: dict = {"model": claude_model, "max_tokens": max_tokens, "messages": msgs}
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return resp.content[0].text.strip()

    def _get_personality_system(self, platform: str = "", topic: str = "") -> str:
        """Returns NarAI's full personality prompt (identity + emotional state + platform + topic)."""
        try:
            from core.personality import PersonalityEngine
            p = platform or getattr(self, "platform", "") or "general"
            t = topic or getattr(self, "topic", "") or getattr(self, "niche", "") or ""
            return PersonalityEngine.get().get_full_prompt(p, t)
        except Exception:
            return "You are NarAI — a confident, direct AI persona. Be bold, data-driven, and empowering."

    def ai(self, prompt: str, system: str = None,
           model: Optional[str] = None, max_tokens: int = 2000,
           temperature: float = 0.7) -> str:
        """
        Send a prompt to OpenAI and return the text response.
        Includes retry logic (3 attempts) and token usage logging.
        If no system prompt is given, NarAI's live personality is injected automatically.
        """
        if system is None:
            system = self._get_personality_system()
        model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        prompt = prompt.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")
        system = system.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")

        def _call():
            return self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

        try:
            resp = _retry(_call, retries=3, delay=2.0, logger=self.logger)
            usage = resp.usage
            if usage:
                _log_token_usage("openai", model,
                                 usage.prompt_tokens, usage.completion_tokens,
                                 self.name)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e).lower()
            # Quota / auth errors → fall back to Claude so bots keep running
            if any(x in err_str for x in ("insufficient_quota", "429", "rate_limit", "invalid_api_key", "authentication")):
                self.logger.warning(f"OpenAI unavailable ({type(e).__name__}) — falling back to Claude")
                try:
                    return self._ai_claude(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                except Exception as ce:
                    self.logger.error(f"Claude fallback also failed: {ce}")
                    raise e
            self.logger.error(f"OpenAI error: {e}")
            raise

    def ai_json(self, prompt: str, system: str = "Respond only with valid JSON.",
                model: Optional[str] = None) -> Dict:
        """Query OpenAI and parse JSON response."""
        import re
        text = self.ai(prompt, system=system, model=model)
        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Response was not valid JSON, returning raw string")
            return {"raw": text}

    # ─── Claude (Anthropic) Client ────────────────────────────────────────────

    @property
    def claude_client(self):
        if self._claude_client is None:
            try:
                from anthropic import Anthropic
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set in .env")
                self._claude_client = Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
        return self._claude_client

    def claude(self, prompt: str, system: str = None,
               model: Optional[str] = None, max_tokens: int = 2000,
               temperature: float = 0.7) -> str:
        """
        Send a prompt to Claude (Anthropic) and return the text response.
        Includes retry logic (3 attempts) and token usage logging.
        If no system prompt is given, NarAI's live personality is injected automatically.
        """
        if system is None:
            system = self._get_personality_system()
        model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        prompt = prompt.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")
        system = system.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")

        def _call():
            return self.claude_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )

        try:
            resp = _retry(_call, retries=3, delay=2.0, logger=self.logger)
            _log_token_usage("anthropic", model,
                             resp.usage.input_tokens, resp.usage.output_tokens,
                             self.name)
            return resp.content[0].text.strip()
        except Exception as e:
            self.logger.error(f"Claude error: {e}")
            raise

    def claude_json(self, prompt: str, system: str = "Respond only with valid JSON.",
                    model: Optional[str] = None) -> Dict:
        """Query Claude and parse JSON response."""
        import re
        text = self.claude(prompt, system=system, model=model)
        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Claude response was not valid JSON, returning raw string")
            return {"raw": text}

    # ─── Output Helpers ────────────────────────────────────────────────────────

    # ─── Topic Deduplication ──────────────────────────────────────────────────

    _USED_TOPICS_FILE = Path(__file__).parent.parent / "data" / "used_topics.json"
    _DEDUP_DAYS = int(os.getenv("DEDUP_DAYS", "7"))  # skip same topic for N days

    def topic_is_duplicate(self, topic: str) -> bool:
        """Return True if this topic was generated within the last DEDUP_DAYS days."""
        slug = hashlib.md5(topic.strip().lower().encode()).hexdigest()
        try:
            raw = json.loads(self._USED_TOPICS_FILE.read_text())
            if isinstance(raw, list):
                raw = {t: "2000-01-01" for t in raw}  # migrate old flat list
            cutoff = (datetime.now() - timedelta(days=self._DEDUP_DAYS)).isoformat()
            if slug in raw and raw[slug] >= cutoff:
                self.logger.info(f"⏭  Skipping duplicate topic (seen {raw[slug][:10]}): {topic[:60]}")
                return True
        except Exception:
            pass
        return False

    def _mark_topic_used(self, topic: str) -> None:
        """Record that this topic was generated now."""
        slug = hashlib.md5(topic.strip().lower().encode()).hexdigest()
        try:
            try:
                raw = json.loads(self._USED_TOPICS_FILE.read_text())
                if isinstance(raw, list):
                    raw = {t: "2000-01-01" for t in raw}
            except Exception:
                raw = {}
            raw[slug] = datetime.now().isoformat()
            self._USED_TOPICS_FILE.write_text(json.dumps(raw, indent=2))
        except Exception as _e:
            self.logger.warning(f"Could not mark topic used: {_e}")

    def save_output(self, content: str, filename: Optional[str] = None,
                    ext: str = "txt", topic: str = "") -> Path:
        """Save string content to the output directory."""
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.name}_{ts}.{ext}"
        out_path = self.output_dir / filename
        out_path.write_text(content, encoding="utf-8")
        self.logger.info(f"💾 Output saved → {out_path}")
        if topic:
            self._mark_topic_used(topic)
        return out_path

    def save_json(self, data: Dict, filename: Optional[str] = None) -> Path:
        """Save dict as JSON to output directory."""
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.name}_{ts}.json"
        out_path = self.output_dir / filename
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        self.logger.info(f"💾 JSON saved → {out_path}")
        return out_path

    # ─── Execution Wrapper ────────────────────────────────────────────────────

    @abstractmethod
    def run(self, **kwargs) -> Any:
        """Main bot logic — override in every subclass."""
        ...

    def execute(self, **kwargs) -> Any:
        """
        Public entry point. Wraps run() with timing, logging, status tracking.
        Call this from orchestrator instead of run() directly.
        """
        self.status = "running"
        self.start_time = time.time()
        self.last_run = datetime.now()
        self.run_count += 1
        self.logger.info(f"▶  Starting {self.name} (run #{self.run_count})")
        try:
            result = self.run(**kwargs)
            elapsed = time.time() - self.start_time
            self.status = "done"
            self.logger.info(f"✅ {self.name} finished in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - self.start_time
            self.status = "error"
            self.logger.error(f"❌ {self.name} failed after {elapsed:.2f}s — {e}", exc_info=True)
            raise

    # ─── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "run_count": self.run_count,
            "last_run": self.last_run.isoformat() if self.last_run else None,
        }

    def __repr__(self):
        return f"<Bot:{self.name} [{self.status}] runs={self.run_count}>"
