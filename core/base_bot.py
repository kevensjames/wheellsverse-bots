#!/usr/bin/env python3
"""
core/base_bot.py
─────────────────────────────────────────────────────────────────────────────
Base class for all 70 WheellsVerse bots.
Every bot inherits from BaseBot and overrides run().
─────────────────────────────────────────────────────────────────────────────
"""

import os
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

# Load root .env
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")


class BaseBot(ABC):
    """
    Abstract base class for every bot in the WheellsVerse ecosystem.
    Provides: logging, OpenAI client, config loading, output saving,
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

        # OpenAI client (lazy — only loaded when needed)
        self._client = None

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

    def ai(self, prompt: str, system: str = "You are a helpful expert assistant.",
           model: Optional[str] = None, max_tokens: int = 2000,
           temperature: float = 0.7) -> str:
        """
        Send a prompt to OpenAI and return the text response.
        Falls back to a stub if no API key is set.
        """
        model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            self.logger.error(f"OpenAI error: {e}")
            raise

    def ai_json(self, prompt: str, system: str = "Respond only with valid JSON.",
                model: Optional[str] = None) -> Dict:
        """Query OpenAI and parse JSON response."""
        import re
        text = self.ai(prompt, system=system, model=model)
        # Strip markdown fences if present
        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Response was not valid JSON, returning raw string")
            return {"raw": text}

    # ─── Output Helpers ────────────────────────────────────────────────────────

    def save_output(self, content: str, filename: Optional[str] = None,
                    ext: str = "txt") -> Path:
        """Save string content to the output directory."""
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.name}_{ts}.{ext}"
        out_path = self.output_dir / filename
        out_path.write_text(content, encoding="utf-8")
        self.logger.info(f"💾 Output saved → {out_path}")
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
