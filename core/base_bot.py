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
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from dotenv import load_dotenv

# Load root .env
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# ─── Operational guards (dedup / compliance / revenue-gate) ──────────────────
# Import lazily with fallbacks so a broken guard module never takes down bots.
try:
    from core import dedup as _guard_dedup  # type: ignore
except Exception:  # pragma: no cover
    _guard_dedup = None
try:
    from core import compliance as _guard_compliance  # type: ignore
except Exception:  # pragma: no cover
    _guard_compliance = None
try:
    from core import revenue_gate as _guard_revenue  # type: ignore
except Exception:  # pragma: no cover
    _guard_revenue = None

# ─── Token usage log ─────────────────────────────────────────────────────────

_TOKEN_LOG = ROOT / "data" / "token_usage.json"
_DAILY_BUDGET_USD = float(os.getenv("ANTHROPIC_DAILY_BUDGET_USD", "1.50"))


class BudgetExceededError(RuntimeError):
    """Raised when the daily Anthropic spend cap is reached."""


def _get_today_anthropic_spend() -> float:
    """Sum today's Anthropic costs from token_usage.json (haiku vs sonnet pricing)."""
    try:
        if not _TOKEN_LOG.exists():
            return 0.0
        records = json.loads(_TOKEN_LOG.read_text())
        today = datetime.now().strftime("%Y-%m-%d")
        total = 0.0
        for r in records:
            if r.get("provider") != "anthropic":
                continue
            if not r.get("ts", "").startswith(today):
                continue
            inp = r.get("prompt_tokens", 0)
            out = r.get("completion_tokens", 0)
            if "haiku" in r.get("model", ""):
                total += (inp / 1_000_000 * 0.80) + (out / 1_000_000 * 4.0)
            else:
                total += (inp / 1_000_000 * 3.0) + (out / 1_000_000 * 15.0)
        return total
    except Exception:
        return 0.0


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


_RETRYABLE = (
    ConnectionError, TimeoutError, OSError,
    # httpx / requests transient errors (checked by name to avoid hard dep)
)
_RETRYABLE_NAMES = {"ConnectError", "ConnectTimeout", "ReadTimeout",
                    "RemoteDisconnected", "ConnectionResetError"}


def _is_retryable(e: Exception) -> bool:
    if isinstance(e, _RETRYABLE):
        return True
    return type(e).__name__ in _RETRYABLE_NAMES


def _retry(fn, retries: int = 3, delay: float = 2.0, logger=None):
    """Retry a callable up to `retries` times with exponential backoff.
    Retries on transient network errors in addition to quota/rate-limit errors.
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            transient = _is_retryable(e) or any(
                x in err_str for x in ("connection", "timeout", "reset", "network")
            )
            if attempt < retries - 1 and transient:
                wait = delay * (2 ** attempt)
                if logger:
                    logger.warning(f"Retry {attempt + 1}/{retries} after {wait:.1f}s: {e}")
                time.sleep(wait)
            elif attempt < retries - 1 and not transient:
                # Non-transient — don't retry, fail fast
                raise
            else:
                raise


class BaseBot(ABC):
    """
    Abstract base class for every bot in the WheellsVerse ecosystem.
    Provides: logging, OpenAI + Claude clients, config loading, output saving,
    error handling, timing, and status reporting.

    Operational guards (applied automatically by execute()):
      - dedup_enabled: skip re-runs with same args within dedup_ttl_seconds
      - revenue_gate_enabled: skip if bot's category is gated AND audience < min
      - compliance recording: every execute() records success/failure so
        109_compliance_agent can tell the truth instead of 'ALL SYSTEMS OK'
    Subclasses override _dedup_fingerprint() if they want a custom key.
    """

    # ─── Operational guard defaults (override per-bot if needed) ──────────
    dedup_enabled: bool = True           # execution-level dedup in execute()
    dedup_ttl_seconds: int = 3600        # 1 hour — one unique run per hour
    revenue_gate_enabled: bool = True    # honored ONLY if category is gated
    _dedup_unstable_keys = ("ts", "timestamp", "now", "time", "run_id", "nonce")

    def __init__(self, name: str, category: str, config_path: Optional[Path] = None):
        self.name = name
        self.category = category
        self.start_time: Optional[float] = None
        self.status = "idle"          # idle | running | done | error
        self.last_run: Optional[datetime] = None
        self.run_count = 0
        self._errors: Deque[str] = deque(maxlen=50)

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
        """Call Claude (Anthropic) — fallback when OpenAI quota is exceeded.

        Routes through core.claude_logged, which handles the budget guard,
        credit-balance normalization, token logging, AND local-backend
        routing (LLM_BACKEND=ollama). Retry logic preserved (3 attempts).
        """
        from core.claude_logged import create as claude_create
        claude_model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

        def _call():
            return claude_create(
                model=claude_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                system=system,
                bot_name=self.name,
            )

        resp = _retry(_call, retries=3, delay=2.0, logger=self.logger)
        return resp.content[0].text.strip()

    def _ai_groq(self, prompt: str, system: str = None,
                 model: str = None, max_tokens: int = 2000,
                 temperature: float = 0.7) -> str:
        """Call Groq — tertiary fallback when both OpenAI and Claude fail.
        Groq exposes an OpenAI-compatible API, so we reuse the openai SDK
        with a base_url override. Requires GROQ_API_KEY env var; raises if missing
        so the outer handler can log and re-raise the original error.
        """
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set — Groq fallback unavailable")
        from openai import OpenAI as _OAI
        groq_model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        client = _OAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=groq_model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()

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

        Routes through core.llm_client.safe_openai_call so the global TPM/RPM
        limiter prevents 429 storms (org-tier ceiling). On insufficient_quota
        or auth failures, falls back to Claude so bots keep running. Token
        usage is logged inside safe_openai_call.
        """
        if system is None:
            system = self._get_personality_system()
        model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        prompt = prompt.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")
        system = system.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")

        from core.llm_client import LLMCapacityTimeout, safe_openai_call
        try:
            resp = safe_openai_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                bot_name=self.name,
            )
            return resp.choices[0].message.content.strip()
        except LLMCapacityTimeout:
            # Limiter waited >timeout for room — Claude is likely just as busy.
            # Surface the timeout so the scheduler can pause this job.
            self.logger.error("OpenAI capacity timeout — pausing job, no Claude fallback")
            raise
        except Exception as e:
            err_str = str(e).lower()
            # Quota / auth errors → fall back to Claude so bots keep running.
            # 429 / rate_limit retained for safety even though limiter should prevent them.
            if any(x in err_str for x in ("insufficient_quota", "429", "rate_limit", "invalid_api_key", "authentication")):
                self.logger.warning(f"OpenAI unavailable ({type(e).__name__}) — falling back to Claude")
                try:
                    return self._ai_claude(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                except Exception as ce:
                    self.logger.warning(f"Claude fallback failed ({type(ce).__name__}) — trying Groq")
                    try:
                        return self._ai_groq(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                    except Exception as ge:
                        self.logger.error(f"All LLM fallbacks failed — OpenAI: {type(e).__name__}; Claude: {ce}; Groq: {ge}")
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
        spend = _get_today_anthropic_spend()
        if spend >= _DAILY_BUDGET_USD:
            raise BudgetExceededError(
                f"Daily Anthropic budget (${_DAILY_BUDGET_USD:.2f}) reached "
                f"(spent ${spend:.4f}) — call blocked"
            )
        if system is None:
            system = self._get_personality_system()
        model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        prompt = prompt.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")
        system = system.encode("utf-8", "ignore").decode("utf-8").replace("\x00", "")

        # Route through claude_logged so LLM_BACKEND=ollama works here too.
        # Budget guard + credit-balance normalization + token logging all
        # happen inside the wrapper.
        from core.claude_logged import create as claude_create

        def _call():
            return claude_create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                bot_name=self.name,
            )

        try:
            resp = _retry(_call, retries=3, delay=2.0, logger=self.logger)
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

    # ─── HTTP Helpers ─────────────────────────────────────────────────────────

    _DEFAULT_HTTP_TIMEOUT = int(os.getenv("BOT_HTTP_TIMEOUT", "30"))

    def http_get(self, url: str, **kwargs) -> "requests.Response":
        """GET with default timeout. Raises on HTTP errors."""
        import requests as _req
        kwargs.setdefault("timeout", self._DEFAULT_HTTP_TIMEOUT)
        r = _req.get(url, **kwargs)
        r.raise_for_status()
        return r

    def http_post(self, url: str, **kwargs) -> "requests.Response":
        """POST with default timeout. Raises on HTTP errors."""
        import requests as _req
        kwargs.setdefault("timeout", self._DEFAULT_HTTP_TIMEOUT)
        r = _req.post(url, **kwargs)
        r.raise_for_status()
        return r

    # ─── Output Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def slugify(text: str, max_len: int = 40) -> str:
        """Filesystem-safe slug: keep alphanumerics, replace everything else with '_'.

        Truncates to ``max_len`` chars first (matching the historical
        ``"".join(c if c.isalnum() else "_" for c in text[:N])`` idiom that was
        copy-pasted across bots).
        """
        return "".join(c if c.isalnum() else "_" for c in (text or "")[:max_len])

    @staticmethod
    def timestamp() -> str:
        """Compact timestamp (``YYYYmmdd_HHMMSS``) used in output filenames."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

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

    # ─── Guard helpers ─────────────────────────────────────────────────────

    def _dedup_fingerprint(self, **kwargs) -> Dict[str, Any]:
        """
        Build a stable key for execution-level dedup. Default strips timestamp-
        like kwargs (which would otherwise defeat dedup by varying every call).
        Override in subclasses to customize — e.g. a book bot may want to
        include `{genre, title}` only, ignoring everything else.
        """
        stable = {k: v for k, v in kwargs.items() if k not in self._dedup_unstable_keys}
        return {
            "bot": self.name,
            "category": self.category,
            "action": kwargs.get("action", ""),
            "kwargs": stable,
        }

    def _check_revenue_gate(self) -> Optional[Dict[str, Any]]:
        """Return a skip-result dict if the revenue gate blocks this bot,
        else None. Factored out so execute() stays readable."""
        if not self.revenue_gate_enabled or _guard_revenue is None:
            return None
        try:
            if _guard_revenue.should_block(self.category):
                info = _guard_revenue.explain(self.category)
                self.logger.warning(
                    "🚦 %s skipped — DISTRIBUTE mode (subs=%s clicks=%s rev=$%s)",
                    self.name,
                    info["metrics"]["subscribers"],
                    info["metrics"]["weekly_clicks"],
                    info["metrics"]["weekly_revenue_usd"],
                )
                return {"skipped": "revenue_gate", "reason": info}
        except Exception as e:
            self.logger.warning("revenue_gate check failed (%s) — proceeding", e)
        return None

    def _check_dedup(self, **kwargs) -> Optional[Dict[str, Any]]:
        """Return a skip-result dict if this run is a duplicate, else None."""
        if not self.dedup_enabled or _guard_dedup is None:
            return None
        try:
            fingerprint = self._dedup_fingerprint(**kwargs)
            if _guard_dedup.is_duplicate(self.name, fingerprint, self.dedup_ttl_seconds):
                self.logger.warning(
                    "🔁 %s skipped — duplicate within %ss (action=%s)",
                    self.name, self.dedup_ttl_seconds, kwargs.get("action", ""),
                )
                return {"skipped": "dedup", "ttl_seconds": self.dedup_ttl_seconds}
        except Exception as e:
            self.logger.warning("dedup check failed (%s) — proceeding", e)
        return None

    def _record_success(self) -> None:
        if _guard_compliance is not None:
            try:
                _guard_compliance.record_success(self.name)
            except Exception as e:
                self.logger.warning("compliance record_success failed: %s", e)

    def _record_failure(self, err: Exception) -> None:
        if _guard_compliance is not None:
            try:
                _guard_compliance.record_failure(self.name, f"{type(err).__name__}: {err}")
            except Exception as e:
                self.logger.warning("compliance record_failure failed: %s", e)

    # ─── Public entry point ────────────────────────────────────────────────

    def execute(self, **kwargs) -> Any:
        """
        Public entry point. Wraps run() with timing, logging, status tracking,
        dedup, revenue-gate, and compliance reporting.

        Order of operations (each guard may short-circuit before run()):
          1. Revenue gate   — is this category gated AND audience < threshold?
          2. Dedup          — did we already run with these args this hour?
          3. run()          — the actual bot work
          4. Record         — tell compliance whether it worked
        """
        self.status = "running"
        self.start_time = time.time()
        self.last_run = datetime.now()
        self.run_count += 1
        self.logger.info(f"▶  Starting {self.name} (run #{self.run_count})")

        # Guard 1: revenue gate — gated categories bail when audience too small
        blocked = self._check_revenue_gate()
        if blocked is not None:
            self.status = "skipped"
            return blocked

        # Guard 2: execution dedup — same args within TTL → skip
        duplicate = self._check_dedup(**kwargs)
        if duplicate is not None:
            self.status = "skipped"
            return duplicate

        try:
            result = self.run(**kwargs)
            elapsed = time.time() - self.start_time
            self.status = "done"
            self.logger.info(f"✅ {self.name} finished in {elapsed:.2f}s")
            self._record_success()
            return result
        except Exception as e:
            elapsed = time.time() - self.start_time
            self.status = "error"
            self._errors.append(f"{datetime.now().isoformat()} {type(e).__name__}: {e}")
            self.logger.error(f"❌ {self.name} failed after {elapsed:.2f}s — {e}", exc_info=True)
            self._record_failure(e)
            raise

    # ─── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "run_count": self.run_count,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "recent_errors": list(self._errors)[-5:],
        }

    def __repr__(self):
        return f"<Bot:{self.name} [{self.status}] runs={self.run_count}>"
