#!/usr/bin/env python3
"""
core/budget_manager.py
─────────────────────────────────────────────────────────────────────────────
Budget Manager — NarAI spends money to make money.

NarAI gets a daily ad budget and autonomously decides:
  1. Which posts to boost (based on FeedbackLoop performance scores)
  2. Which platform to boost on (Facebook Ads or TikTok Ads)
  3. How much to spend per boost ($1–$20)
  4. When to stop a boost (low ROI detected)
  5. Daily ROI report → Telegram

Budget rules:
  • Never exceed DAILY_AD_BUDGET
  • Only boost posts scoring above BOOST_SCORE_THRESHOLD
  • Minimum 2h between boosts (rate limit)
  • Stop a campaign if CTR drops below MIN_CTR after 6h

.env keys:
  DAILY_AD_BUDGET         — daily spend cap in USD (default: $10)
  BOOST_SCORE_THRESHOLD   — min FeedbackLoop score to qualify for boost (default: 500)
  FB_AD_ACCOUNT_ID        — Facebook Ad Account ID (act_XXXXX)
  TIKTOK_ADVERTISER_ID    — TikTok Ads advertiser ID

Storage: data/budget_ledger.json
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR     = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
LEDGER_FILE  = DATA_DIR / "budget_ledger.json"

logger = logging.getLogger("budget_manager")

DAILY_BUDGET    = float(os.getenv("DAILY_AD_BUDGET", "10.0"))
SCORE_THRESHOLD = float(os.getenv("BOOST_SCORE_THRESHOLD", "500"))
MIN_BOOST       = 1.0    # minimum spend per boost
MAX_BOOST       = 20.0   # maximum spend per boost
MIN_CTR         = 0.01   # 1% CTR minimum to keep running
BOOST_COOLDOWN  = 7200   # 2h between boosts


# ─── Spend record ─────────────────────────────────────────────────────────────

class SpendRecord:
    def __init__(self, post_id: str, platform: str, amount: float,
                 campaign_id: str = "", topic: str = ""):
        self.post_id     = post_id
        self.platform    = platform
        self.amount      = amount
        self.campaign_id = campaign_id
        self.topic       = topic
        self.spent_at    = datetime.now().isoformat()
        self.status      = "active"   # active / paused / completed
        self.impressions = 0
        self.clicks      = 0
        self.conversions = 0
        self.revenue     = 0.0

    @property
    def ctr(self) -> float:
        return self.clicks / max(self.impressions, 1)

    @property
    def roi(self) -> float:
        return (self.revenue - self.amount) / max(self.amount, 0.01)

    def to_dict(self) -> Dict:
        return {**self.__dict__, "ctr": self.ctr, "roi": round(self.roi, 3)}

    @classmethod
    def from_dict(cls, d: Dict) -> "SpendRecord":
        r = cls(d["post_id"], d["platform"], d["amount"],
                d.get("campaign_id",""), d.get("topic",""))
        for k, v in d.items():
            if k not in ("ctr","roi") and hasattr(r, k):
                setattr(r, k, v)
        return r


# ─── Budget Manager ───────────────────────────────────────────────────────────

class BudgetManager:
    """
    Autonomous ad budget controller.
    Monitors FeedbackLoop, decides what to boost, tracks ROI.
    """

    _instance: Optional["BudgetManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._ledger: List[SpendRecord] = []
        self._last_boost_time = 0.0
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._file_lock = threading.Lock()
        self._load()

    @classmethod
    def get(cls) -> "BudgetManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if LEDGER_FILE.exists():
            try:
                raw = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
                self._ledger = [SpendRecord.from_dict(d) for d in raw.get("ledger", [])]
                logger.info(f"[Budget] Loaded {len(self._ledger)} spend records")
            except Exception as e:
                logger.warning(f"[Budget] Load error: {e}")

    def _save(self):
        with self._file_lock:
            try:
                LEDGER_FILE.write_text(json.dumps(
                    {"ledger": [r.to_dict() for r in self._ledger]},
                    indent=2
                ), encoding="utf-8")
            except Exception as e:
                logger.error(f"[Budget] Save error: {e}")

    # ── Budget tracking ───────────────────────────────────────────────────────

    def today_spent(self) -> float:
        today = datetime.now().date().isoformat()
        return sum(
            r.amount for r in self._ledger
            if r.spent_at[:10] == today
        )

    def today_remaining(self) -> float:
        return max(0.0, DAILY_BUDGET - self.today_spent())

    def today_revenue(self) -> float:
        today = datetime.now().date().isoformat()
        return sum(r.revenue for r in self._ledger if r.spent_at[:10] == today)

    def today_roi(self) -> float:
        spent   = self.today_spent()
        revenue = self.today_revenue()
        return (revenue - spent) / max(spent, 0.01)

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="BudgetManager"
        )
        self._thread.start()
        logger.info(f"[Budget] Started — daily budget: ${DAILY_BUDGET:.2f}")

    def stop(self):
        self._running = False

    # ── Main loop (every 30 min) ──────────────────────────────────────────────

    def _run(self):
        while self._running:
            try:
                self._evaluate_boosts()
                self._check_active_campaigns()
            except Exception as e:
                logger.error(f"[Budget] Loop error: {e}")
            time.sleep(1800)  # 30 min

    def _evaluate_boosts(self):
        """Find high-performing posts and boost the best one."""
        remaining = self.today_remaining()
        if remaining < MIN_BOOST:
            logger.info(f"[Budget] Budget exhausted (${self.today_spent():.2f} spent)")
            return

        if time.time() - self._last_boost_time < BOOST_COOLDOWN:
            return

        # Find best qualifying post
        try:
            from core.feedback_loop import FeedbackLoop
            fl      = FeedbackLoop.get()
            posts   = sorted(fl._posts.values(), key=lambda p: p.score, reverse=True)
            already = {r.post_id for r in self._ledger}

            for post in posts:
                if post.score < SCORE_THRESHOLD:
                    break
                if post.post_id in already:
                    continue
                if post.platform not in ("facebook", "tiktok", "instagram"):
                    continue

                # Calculate boost amount: proportional to score, capped
                boost = min(
                    MAX_BOOST,
                    max(MIN_BOOST, remaining * 0.4),   # use 40% of remaining
                )

                result = self.boost_post(
                    post_id=post.post_id,
                    platform=post.platform,
                    topic=post.topic,
                    amount=boost,
                )
                if result.get("status") == "boosted":
                    self._last_boost_time = time.time()
                    self._notify(
                        f"📈 BOOSTED\n{post.topic[:50]}\n"
                        f"Platform: {post.platform} | ${boost:.2f}\n"
                        f"Budget remaining: ${self.today_remaining():.2f}"
                    )
                    break
        except Exception as e:
            logger.warning(f"[Budget] Evaluate error: {e}")

    def _check_active_campaigns(self):
        """Check running campaigns, pause those with low CTR."""
        active = [r for r in self._ledger if r.status == "active"]
        for record in active:
            # Update stats from platform
            self._update_campaign_stats(record)
            # Check CTR after 6h
            age_hours = (datetime.now() -
                         datetime.fromisoformat(record.spent_at)).seconds / 3600
            if age_hours >= 6 and record.impressions > 100 and record.ctr < MIN_CTR:
                record.status = "paused"
                self._pause_campaign(record)
                logger.info(
                    f"[Budget] Paused campaign {record.campaign_id} "
                    f"(CTR={record.ctr:.2%} < {MIN_CTR:.0%})"
                )
            self._save()

    # ── Boost actions ─────────────────────────────────────────────────────────

    def boost_post(self, post_id: str, platform: str, topic: str,
                   amount: float) -> Dict:
        """
        Boost a post on its platform via Ads API.
        Returns {"status": "boosted", "campaign_id": "..."} or {"error": "..."}
        """
        logger.info(f"[Budget] Boosting {post_id} on {platform} for ${amount:.2f}")

        if platform == "facebook":
            result = self._boost_facebook(post_id, amount)
        elif platform == "tiktok":
            result = self._boost_tiktok(post_id, amount)
        else:
            # Simulate boost for platforms without direct API
            result = {"status": "simulated", "campaign_id": f"sim_{post_id[:8]}"}

        if result.get("status") in ("boosted", "simulated"):
            record = SpendRecord(
                post_id=post_id,
                platform=platform,
                amount=amount,
                campaign_id=result.get("campaign_id",""),
                topic=topic,
            )
            self._ledger.append(record)
            self._save()
            logger.info(f"[Budget] Boost recorded: ${amount:.2f} on {platform}")
            return result

        return result

    def record_revenue(self, post_id: str, revenue: float):
        """Record affiliate revenue attributed to a boosted post."""
        for r in self._ledger:
            if r.post_id == post_id and r.status == "active":
                r.revenue += revenue
                self._save()
                logger.info(f"[Budget] Revenue ${revenue:.2f} → {post_id}")
                break

    # ── Platform ad APIs ──────────────────────────────────────────────────────

    def _boost_facebook(self, post_id: str, amount: float) -> Dict:
        """Boost a Facebook post via Graph API Ads."""
        token      = os.getenv("FACEBOOK_PAGE_TOKEN")
        account_id = os.getenv("FB_AD_ACCOUNT_ID")  # act_XXXXXXX
        page_id    = os.getenv("FACEBOOK_PAGE_ID")

        if not (token and account_id):
            return {"status": "simulated", "campaign_id": f"sim_{post_id[:8]}",
                    "note": "Set FB_AD_ACCOUNT_ID to enable real Facebook Ads"}

        try:
            # Create ad campaign
            fb_post_id = post_id.replace("fb_", "")
            resp = requests.post(
                f"https://graph.facebook.com/v19.0/{account_id}/campaigns",
                params={"access_token": token},
                json={
                    "name":       f"WheellsVerse Boost {fb_post_id[:8]}",
                    "objective":  "LINK_CLICKS",
                    "status":     "ACTIVE",
                    "special_ad_categories": [],
                    "daily_budget": int(amount * 100),  # cents
                },
                timeout=20,
            )
            if resp.status_code in (200, 201):
                campaign_id = resp.json().get("id","")
                logger.info(f"[Budget] FB campaign created: {campaign_id}")
                return {"status": "boosted", "campaign_id": campaign_id}
            return {"error": f"FB Ads error {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def _boost_tiktok(self, post_id: str, amount: float) -> Dict:
        """Boost a TikTok post via TikTok Ads API."""
        advertiser_id = os.getenv("TIKTOK_ADVERTISER_ID")
        access_token  = os.getenv("TIKTOK_ACCESS_TOKEN")

        if not (advertiser_id and access_token):
            return {"status": "simulated", "campaign_id": f"sim_{post_id[:8]}",
                    "note": "Set TIKTOK_ADVERTISER_ID to enable real TikTok Ads"}

        try:
            resp = requests.post(
                "https://business-api.tiktok.com/open_api/v1.3/campaign/create/",
                headers={"Access-Token": access_token,
                         "Content-Type": "application/json"},
                json={
                    "advertiser_id":   advertiser_id,
                    "campaign_name":   f"WheellsVerse {post_id[:8]}",
                    "campaign_type":   "REGULAR_CAMPAIGN",
                    "objective_type":  "TRAFFIC",
                    "budget_mode":     "BUDGET_MODE_DAY",
                    "budget":          amount,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                campaign_id = resp.json().get("data",{}).get("campaign_id","")
                return {"status": "boosted", "campaign_id": str(campaign_id)}
            return {"error": resp.text[:200]}
        except Exception as e:
            return {"error": str(e)}

    def _update_campaign_stats(self, record: SpendRecord):
        """Pull live stats from the ad platform."""
        try:
            if record.platform == "facebook" and not record.campaign_id.startswith("sim_"):
                token = os.getenv("FACEBOOK_PAGE_TOKEN")
                if not token:
                    return
                resp = requests.get(
                    f"https://graph.facebook.com/v19.0/{record.campaign_id}/insights",
                    params={
                        "fields":       "impressions,clicks,ctr",
                        "access_token": token,
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", [{}])[0]
                    record.impressions = int(data.get("impressions", 0))
                    record.clicks      = int(data.get("clicks", 0))
        except Exception:
            pass

    def _pause_campaign(self, record: SpendRecord):
        """Pause a running ad campaign."""
        try:
            if record.platform == "facebook" and not record.campaign_id.startswith("sim_"):
                token = os.getenv("FACEBOOK_PAGE_TOKEN")
                if token:
                    requests.post(
                        f"https://graph.facebook.com/v19.0/{record.campaign_id}",
                        params={"access_token": token},
                        json={"status": "PAUSED"},
                        timeout=10,
                    )
        except Exception:
            pass

    # ── Reporting ─────────────────────────────────────────────────────────────

    def daily_report(self) -> Dict:
        today     = datetime.now().date().isoformat()
        today_rec = [r for r in self._ledger if r.spent_at[:10] == today]
        return {
            "date":           today,
            "daily_budget":   DAILY_BUDGET,
            "spent":          round(self.today_spent(), 2),
            "remaining":      round(self.today_remaining(), 2),
            "revenue":        round(self.today_revenue(), 2),
            "roi":            round(self.today_roi() * 100, 1),
            "boosts_today":   len(today_rec),
            "active_boosts":  sum(1 for r in today_rec if r.status == "active"),
            "campaigns":      [r.to_dict() for r in today_rec],
        }

    def summary(self) -> Dict:
        all_spent   = sum(r.amount for r in self._ledger)
        all_revenue = sum(r.revenue for r in self._ledger)
        return {
            "daily_budget":    DAILY_BUDGET,
            "today_spent":     round(self.today_spent(), 2),
            "today_remaining": round(self.today_remaining(), 2),
            "today_roi_pct":   round(self.today_roi() * 100, 1),
            "all_time_spent":  round(all_spent, 2),
            "all_time_revenue":round(all_revenue, 2),
            "all_time_roi_pct":round((all_revenue - all_spent) / max(all_spent, 0.01) * 100, 1),
            "total_boosts":    len(self._ledger),
            "active_boosts":   sum(1 for r in self._ledger if r.status == "active"),
        }

    def _notify(self, message: str):
        try:
            token   = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if token and chat_id:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": f"💰 Budget Manager\n\n{message}"},
                    timeout=8,
                )
        except Exception:
            pass
