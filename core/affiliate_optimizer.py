#!/usr/bin/env python3
"""
core/affiliate_optimizer.py
─────────────────────────────────────────────────────────────────────────────
Dynamic Affiliate Optimizer — the system that picks the winning program.

How it works:
  1. For each niche (crypto, investing, ai_tools, etc.) it runs A/B tests
     with 2-3 competing affiliate programs simultaneously
  2. Tracks real clicks from click_tracker.py per program per post
  3. After MIN_DATA_POINTS clicks, calculates conversion rate per program
  4. Automatically promotes the winner and demotes the losers
  5. Injects winning links into all future content via get_best_link(niche)

Example:
  crypto niche → tests: Coinbase vs Binance vs ClickBank crypto
  After 50 clicks: Coinbase 4.2% CTR, Binance 1.8%, ClickBank 0.9%
  → Coinbase wins. All future crypto content uses Coinbase link.
  → Re-tests every 7 days to adapt to market changes.

Integrates with:
  - FeedbackLoop: reads engagement scores per post
  - click_tracker: reads raw click data per affiliate partner
  - monetization: overrides default link injection
  - All content bots: call get_best_link(niche) instead of hardcoded URLs

Storage: data/affiliate_optimizer.json
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OPT_FILE = DATA_DIR / "affiliate_optimizer.json"

logger = logging.getLogger("affiliate_optimizer")

MIN_DATA_POINTS = 20      # clicks before declaring a winner
RETEST_DAYS = 7       # re-run tests every 7 days
WINNER_THRESHOLD = 1.5     # winner must be 1.5x better than runner-up
CHECK_INTERVAL = 3600    # check every hour


# ─── All affiliate programs per niche ────────────────────────────────────────

def _build_program_pool() -> Dict[str, List[Dict]]:
    """Build the full test pool from .env values."""
    return {
        "crypto": [
            {"name": "coinbase", "url": os.getenv("AFFILIATE_COINBASE_URL", ""),
             "label": "Coinbase — $10 BTC signup", "commission": "$10/signup"},
            {"name": "binance", "url": os.getenv("AFFILIATE_BINANCE_URL", ""),
             "label": "Binance — 50% commission", "commission": "50% fees"},
            {"name": "clickbank", "url": os.getenv("AFFILIATE_CLICKBANK_URL", ""),
             "label": "ClickBank Crypto", "commission": "50-75%"},
        ],
        "investing": [
            {"name": "webull", "url": os.getenv("AFFILIATE_WEBULL_URL", ""),
             "label": "Webull — free stocks", "commission": "$3-225/signup"},
            {"name": "coinbase", "url": os.getenv("AFFILIATE_COINBASE_URL", ""),
             "label": "Coinbase — $10 BTC", "commission": "$10/signup"},
            {"name": "clickbank", "url": os.getenv("AFFILIATE_CLICKBANK_URL", ""),
             "label": "ClickBank Investing", "commission": "50-75%"},
        ],
        "ai_tools": [
            {"name": "jasper", "url": os.getenv("AFFILIATE_JASPER_URL", ""),
             "label": "Jasper AI — 25% recurring", "commission": "25% recurring"},
            {"name": "appsumo", "url": os.getenv("AFFILIATE_APPSUMO_URL", ""),
             "label": "AppSumo — up to $200/sale", "commission": "$200/sale"},
            {"name": "convertkit", "url": os.getenv("AFFILIATE_CONVERTKIT_URL", ""),
             "label": "ConvertKit — 30% recurring", "commission": "30% recurring"},
        ],
        "passive_income": [
            {"name": "clickbank", "url": os.getenv("AFFILIATE_CLICKBANK_URL", ""),
             "label": "ClickBank — 75% commission", "commission": "50-75%"},
            {"name": "convertkit", "url": os.getenv("AFFILIATE_CONVERTKIT_URL", ""),
             "label": "ConvertKit — 30% recurring", "commission": "30% recurring"},
            {"name": "bluehost", "url": os.getenv("AFFILIATE_BLUEHOST_URL", ""),
             "label": "Bluehost — $65/signup", "commission": "$65/signup"},
        ],
        "blogging": [
            {"name": "bluehost", "url": os.getenv("AFFILIATE_BLUEHOST_URL", ""),
             "label": "Bluehost — $65/signup", "commission": "$65/signup"},
            {"name": "convertkit", "url": os.getenv("AFFILIATE_CONVERTKIT_URL", ""),
             "label": "ConvertKit — 30% recurring", "commission": "30% recurring"},
            {"name": "jasper", "url": os.getenv("AFFILIATE_JASPER_URL", ""),
             "label": "Jasper AI — 25% recurring", "commission": "25% recurring"},
        ],
        "email_marketing": [
            {"name": "convertkit", "url": os.getenv("AFFILIATE_CONVERTKIT_URL", ""),
             "label": "ConvertKit — 30% recurring", "commission": "30% recurring"},
            {"name": "bluehost", "url": os.getenv("AFFILIATE_BLUEHOST_URL", ""),
             "label": "Bluehost — $65/signup", "commission": "$65/signup"},
            {"name": "jasper", "url": os.getenv("AFFILIATE_JASPER_URL", ""),
             "label": "Jasper AI", "commission": "25% recurring"},
        ],
        "general": [
            {"name": "coinbase", "url": os.getenv("AFFILIATE_COINBASE_URL", ""),
             "label": "Coinbase", "commission": "$10/signup"},
            {"name": "webull", "url": os.getenv("AFFILIATE_WEBULL_URL", ""),
             "label": "Webull", "commission": "$3-225/signup"},
            {"name": "jasper", "url": os.getenv("AFFILIATE_JASPER_URL", ""),
             "label": "Jasper AI", "commission": "25% recurring"},
        ],
    }


# ─── Test record ──────────────────────────────────────────────────────────────

class AffiliateTest:
    """Tracks an A/B test between affiliate programs for a niche."""

    def __init__(self, niche: str, programs: List[Dict]):
        self.niche = niche
        self.programs = programs          # list of program dicts
        self.clicks: Dict[str, int] = {p["name"]: 0 for p in programs}
        self.conversions: Dict[str, int] = {p["name"]: 0 for p in programs}
        self.revenue: Dict[str, float] = {p["name"]: 0.0 for p in programs}
        self.started_at = datetime.now().isoformat()
        self.winner: Optional[str] = None
        self.winner_url: Optional[str] = None
        self.next_retest = (datetime.now() + timedelta(days=RETEST_DAYS)).isoformat()
        self.status = "testing"   # testing / winner_found / retesting

    def record_click(self, program_name: str):
        if program_name in self.clicks:
            self.clicks[program_name] += 1

    def record_conversion(self, program_name: str, revenue: float = 0.0):
        if program_name in self.conversions:
            self.conversions[program_name] += 1
            self.revenue[program_name] += revenue

    def ctr(self, program_name: str) -> float:
        total = sum(self.clicks.values())
        return self.clicks.get(program_name, 0) / max(total, 1)

    def conversion_rate(self, program_name: str) -> float:
        clicks = self.clicks.get(program_name, 0)
        return self.conversions.get(program_name, 0) / max(clicks, 1)

    def total_clicks(self) -> int:
        return sum(self.clicks.values())

    def evaluate(self) -> Optional[str]:
        """
        Determine winner if we have enough data.
        Returns winning program name or None.
        """
        if self.total_clicks() < MIN_DATA_POINTS:
            return None

        # Score = CTR × 0.4 + conversion_rate × 0.6
        scores = {}
        for p in self.programs:
            name = p["name"]
            scores[name] = (self.ctr(name) * 0.4 +
                            self.conversion_rate(name) * 0.6)

        if not scores:
            return None

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else (None, 0)

        if best[1] == 0:
            return None

        # Winner must be WINNER_THRESHOLD better than runner-up
        if runner[1] == 0 or best[1] / max(runner[1], 0.0001) >= WINNER_THRESHOLD:
            self.winner = best[0]
            prog = next((p for p in self.programs if p["name"] == best[0]), {})
            self.winner_url = prog.get("url", "")
            self.status = "winner_found"
            return self.winner

        return None

    def should_retest(self) -> bool:
        if self.status != "winner_found":
            return False
        return datetime.now() >= datetime.fromisoformat(self.next_retest)

    def to_dict(self) -> Dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, d: Dict) -> "AffiliateTest":
        t = cls(d["niche"], d.get("programs", []))
        for k, v in d.items():
            setattr(t, k, v)
        return t


# ─── Optimizer engine ─────────────────────────────────────────────────────────

class AffiliateOptimizer:
    """
    Main optimizer — runs A/B tests and picks winning affiliate programs.
    """

    _instance: Optional["AffiliateOptimizer"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._tests: Dict[str, AffiliateTest] = {}
        self._file_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._load()
        self._init_missing_tests()

    @classmethod
    def get(cls) -> "AffiliateOptimizer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if OPT_FILE.exists():
            try:
                raw = json.loads(OPT_FILE.read_text(encoding="utf-8"))
                self._tests = {
                    niche: AffiliateTest.from_dict(d)
                    for niche, d in raw.get("tests", {}).items()
                }
                logger.info(f"[AffOpt] Loaded tests for {list(self._tests.keys())}")
            except Exception as e:
                logger.warning(f"[AffOpt] Load error: {e}")

    def _save(self):
        with self._file_lock:
            try:
                OPT_FILE.write_text(json.dumps(
                    {"tests": {n: t.to_dict() for n, t in self._tests.items()}},
                    indent=2
                ), encoding="utf-8")
            except Exception as e:
                logger.error(f"[AffOpt] Save error: {e}")

    def _init_missing_tests(self):
        """Create tests for any niches not yet initialized."""
        pool = _build_program_pool()
        for niche, programs in pool.items():
            if niche not in self._tests:
                valid = [p for p in programs if p.get("url")]
                if valid:
                    self._tests[niche] = AffiliateTest(niche, valid)
                    logger.info(f"[AffOpt] Initialized test for {niche}: "
                                f"{[p['name'] for p in valid]}")
        self._save()

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="AffiliateOptimizer"
        )
        self._thread.start()
        logger.info("[AffOpt] Started — evaluating every hour")

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                self._sync_clicks()
                self._evaluate_all()
                self._check_retests()
            except Exception as e:
                logger.error(f"[AffOpt] Loop error: {e}")
            time.sleep(CHECK_INTERVAL)

    # ── Click sync from click_tracker ─────────────────────────────────────────

    def _sync_clicks(self):
        """Read click data from click_tracker and update tests."""
        try:
            clicks_file = DATA_DIR / "clicks.json"
            if not clicks_file.exists():
                return
            raw = json.loads(clicks_file.read_text())
            clicks = raw if isinstance(raw, list) else raw.get("clicks", [])

            for click in clicks:
                partner = click.get("partner", "")
                niche = click.get("niche", "general")
                # Find which test this click belongs to
                test = self._tests.get(niche) or self._tests.get("general")
                if test:
                    test.record_click(partner)

            self._save()
        except Exception as e:
            logger.debug(f"[AffOpt] Click sync error: {e}")

    # ── Evaluation ────────────────────────────────────────────────────────────

    def _evaluate_all(self):
        """Check all tests for winners."""
        for niche, test in self._tests.items():
            if test.status == "testing":
                winner = test.evaluate()
                if winner:
                    winner_program = next((p for p in test.programs if p["name"] == winner), {})
                    test.winner_program = winner_program  # store on test for downstream use
                    logger.info(
                        f"[AffOpt] 🏆 WINNER [{niche}]: {winner} "
                        f"(CTR={test.ctr(winner):.2%}, "
                        f"CVR={test.conversion_rate(winner):.2%})"
                    )
                    self._notify_winner(niche, winner, test)
                    self._save()

    def _check_retests(self):
        """Reset tests that are due for retesting."""
        for niche, test in self._tests.items():
            if test.should_retest():
                logger.info(f"[AffOpt] Retesting {niche}")
                pool = _build_program_pool()
                valid = [p for p in pool.get(niche, []) if p.get("url")]
                self._tests[niche] = AffiliateTest(niche, valid)
                self._save()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_best_link(self, niche: str) -> Dict:
        """
        Get the best affiliate link for a niche.
        Returns {"name": str, "url": str, "label": str, "status": str}

        Bots call this instead of using hardcoded affiliate URLs.
        """
        test = self._tests.get(niche) or self._tests.get("general")
        if not test:
            return self._fallback_link(niche)

        if test.winner and test.winner_url:
            prog = next((p for p in test.programs if p["name"] == test.winner), {})
            return {
                "name": test.winner,
                "url": test.winner_url,
                "label": prog.get("label", test.winner),
                "status": "winner",
                "niche": niche,
            }

        # Still testing — rotate to gather data
        testing = [p for p in test.programs if p.get("url")]
        if not testing:
            return self._fallback_link(niche)

        # Weighted random: favour programs with fewer clicks (explore)
        weights = [1 / max(test.clicks.get(p["name"], 0) + 1, 1) for p in testing]
        chosen = random.choices(testing, weights=weights, k=1)[0]
        return {
            "name": chosen["name"],
            "url": chosen["url"],
            "label": chosen["label"],
            "status": "testing",
            "niche": niche,
        }

    def record_click(self, niche: str, program_name: str):
        """Record a click for a program in a niche."""
        test = self._tests.get(niche)
        if test:
            test.record_click(program_name)
            self._save()

    def record_conversion(self, niche: str, program_name: str, revenue: float = 0.0):
        """Record a conversion (signup/purchase) for a program."""
        test = self._tests.get(niche)
        if test:
            test.record_conversion(program_name, revenue)
            self._save()
            logger.info(f"[AffOpt] Conversion: {program_name} ({niche}) +${revenue:.2f}")

    def get_all_winners(self) -> Dict[str, Dict]:
        """Return the current winner for every niche."""
        winners = {}
        for niche, test in self._tests.items():
            winners[niche] = {
                "winner": test.winner,
                "url": test.winner_url,
                "status": test.status,
                "clicks": test.clicks,
                "total_clicks": test.total_clicks(),
            }
        return winners

    def summary(self) -> Dict:
        winners_found = sum(1 for t in self._tests.values() if t.winner)
        return {
            "niches_tracked": len(self._tests),
            "winners_found": winners_found,
            "still_testing": len(self._tests) - winners_found,
            "total_clicks": sum(t.total_clicks() for t in self._tests.values()),
            "winners": {
                niche: {"winner": t.winner, "clicks": t.total_clicks()}
                for niche, t in self._tests.items() if t.winner
            },
            "testing": {
                niche: {"clicks_so_far": t.total_clicks(),
                        "need_more": max(0, MIN_DATA_POINTS - t.total_clicks())}
                for niche, t in self._tests.items() if not t.winner
            }
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fallback_link(self, niche: str) -> Dict:
        fallbacks = {
            "crypto": ("coinbase", os.getenv("AFFILIATE_COINBASE_URL", ""), "Coinbase"),
            "investing": ("webull", os.getenv("AFFILIATE_WEBULL_URL", ""), "Robinhood"),
            "ai_tools": ("jasper", os.getenv("AFFILIATE_JASPER_URL", ""), "Jasper AI"),
            "passive_income": ("clickbank", os.getenv("AFFILIATE_CLICKBANK_URL", ""), "ClickBank"),
            "blogging": ("bluehost", os.getenv("AFFILIATE_BLUEHOST_URL", ""), "Bluehost"),
            "email_marketing": ("convertkit", os.getenv("AFFILIATE_CONVERTKIT_URL", ""), "ConvertKit"),
        }
        name, url, label = fallbacks.get(niche, ("coinbase", os.getenv("AFFILIATE_COINBASE_URL", ""), "Coinbase"))
        return {"name": name, "url": url, "label": label, "status": "fallback", "niche": niche}

    def _notify_winner(self, niche: str, winner: str, test: AffiliateTest):
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if not (token and chat_id):
                return
            msg = (
                f"🏆 AFFILIATE WINNER FOUND\n\n"
                f"Niche: {niche}\n"
                f"Winner: {winner}\n"
                f"CTR: {test.ctr(winner):.2%}\n"
                f"Conversion: {test.conversion_rate(winner):.2%}\n"
                f"Clicks tested: {test.total_clicks()}\n"
                f"Retest in: {RETEST_DAYS} days"
            )
            import requests as _req
            _req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg},
                timeout=8,
            )
        except Exception:
            pass


def get_best_link(niche: str = "general") -> Dict:
    """Convenience function — bots call this for the optimal affiliate link."""
    return AffiliateOptimizer.get().get_best_link(niche)
