#!/usr/bin/env python3
"""
core/decision_engine.py
─────────────────────────────────────────────────────────────────────────────
Decision Engine — the autonomous "brain" of WheellsVerse.

Analyzes system state every N minutes and fires actions automatically:
  • Rule-based triggers  (always on)
  • AI-assisted analysis (optional, uses GPT)
  • Feedback from bot outputs
  • Market intelligence   — crypto price alerts via integrations
  • Trend intelligence    — Google Trends + Reddit → content pipeline
  • System health         — retry failed bots, escalate alerts

Rule examples:
  IF hour == 8 AND morning_pipeline_not_ran  → run morning_blast
  IF bot fails 3x consecutively              → run debugging_assistant
  IF no activity for 12h                     → run growth_sprint
  IF it's Monday 7am                         → run weekly_report
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).parent.parent
logger = logging.getLogger("decision_engine")


# ─── Rule system ──────────────────────────────────────────────────────────────

class Rule:
    """
    A single decision rule: condition → action.
    condition_fn receives the system state dict and returns bool.
    """

    def __init__(
        self,
        name: str,
        description: str,
        condition_fn: Callable[[Dict], bool],
        action: Dict[str, Any],
        priority: int = 5,
        cooldown_minutes: int = 60,
        enabled: bool = True,
    ):
        self.name = name
        self.description = description
        self.condition_fn = condition_fn
        self.action = action
        self.priority = priority        # 1=highest, 10=lowest
        self.cooldown_minutes = cooldown_minutes
        self.enabled = enabled
        self.last_triggered: Optional[float] = None
        self.trigger_count: int = 0

    def can_trigger(self) -> bool:
        if not self.enabled:
            return False
        if self.last_triggered is None:
            return True
        elapsed = (time.time() - self.last_triggered) / 60
        return elapsed >= self.cooldown_minutes

    def evaluate(self, state: Dict) -> bool:
        if not self.can_trigger():
            return False
        try:
            return bool(self.condition_fn(state))
        except Exception as e:
            logger.debug(f"Rule '{self.name}' condition error: {e}")
            return False

    def mark_triggered(self):
        self.last_triggered = time.time()
        self.trigger_count += 1

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "cooldown_minutes": self.cooldown_minutes,
            "enabled": self.enabled,
            "trigger_count": self.trigger_count,
            "last_triggered": (
                datetime.fromtimestamp(self.last_triggered).isoformat()
                if self.last_triggered else None
            ),
            "action": self.action,
        }


def _build_default_rules() -> List[Rule]:
    """Factory: returns the default set of decision rules."""

    now = datetime.now

    return [
        # ── Time-based pipeline triggers ──────────────────────────────────────
        Rule(
            name="morning_blast",
            description="Run morning content + trend pipeline every day at 8am",
            condition_fn=lambda s: (
                now().hour == 8 and
                not s.get("morning_ran_today", False)
            ),
            action={"type": "run_pipeline", "pipeline": "morning_blast"},
            priority=1,
            cooldown_minutes=720,  # 12h min between triggers
        ),
        Rule(
            name="daily_sales",
            description="Run sales engine pipeline every day at 9am",
            condition_fn=lambda s: (
                now().hour == 9 and
                not s.get("sales_ran_today", False)
            ),
            action={"type": "run_pipeline", "pipeline": "sales_engine"},
            priority=2,
            cooldown_minutes=720,
        ),
        Rule(
            name="social_domination_daily",
            description="Run social domination pipeline at 10am daily",
            condition_fn=lambda s: (
                now().hour == 10 and
                not s.get("social_ran_today", False)
            ),
            action={"type": "run_pipeline", "pipeline": "social_domination"},
            priority=3,
            cooldown_minutes=720,
        ),
        Rule(
            name="weekly_report_monday",
            description="Generate weekly report every Monday at 7am",
            condition_fn=lambda s: (
                now().weekday() == 0 and  # Monday
                now().hour == 7 and
                not s.get("weekly_report_ran", False)
            ),
            action={"type": "run_pipeline", "pipeline": "weekly_report"},
            priority=2,
            cooldown_minutes=6 * 24 * 60,  # 6 days
        ),
        Rule(
            name="business_intelligence_friday",
            description="Run business intelligence pipeline every Friday at 4pm",
            condition_fn=lambda s: (
                now().weekday() == 4 and  # Friday
                now().hour == 16
            ),
            action={"type": "run_pipeline", "pipeline": "business_intelligence"},
            priority=3,
            cooldown_minutes=5 * 24 * 60,
        ),

        # ── Bot failure recovery ───────────────────────────────────────────────
        Rule(
            name="retry_failed_bots",
            description="Retry bots that have failed — run debugging assistant",
            condition_fn=lambda s: len(s.get("consecutive_failures", [])) > 0,
            action={"type": "run_bot", "bot": "problem_solving/57_debugging_assistant"},
            priority=1,
            cooldown_minutes=30,
        ),
        Rule(
            name="mass_failure_alert",
            description="If >5 bots failed, run recovery check",
            condition_fn=lambda s: s.get("total_failed", 0) >= 5,
            action={"type": "run_bot", "bot": "specialized/70_reporting_dashboard"},
            priority=1,
            cooldown_minutes=120,
        ),

        # ── Inactivity triggers ───────────────────────────────────────────────
        Rule(
            name="no_activity_growth",
            description="If no bots ran in 12+ hours, trigger growth pipeline",
            condition_fn=lambda s: s.get("hours_since_last_run", 0) >= 12,
            action={"type": "run_pipeline", "pipeline": "growth_sprint"},
            priority=5,
            cooldown_minutes=12 * 60,
        ),
        Rule(
            name="no_content_today",
            description="If no content generated today by 6pm, run content machine",
            condition_fn=lambda s: (
                now().hour >= 18 and
                not s.get("content_ran_today", False)
            ),
            action={"type": "run_pipeline", "pipeline": "content_machine"},
            priority=4,
            cooldown_minutes=720,
        ),

        # ── Smart triggers ────────────────────────────────────────────────────
        Rule(
            name="customer_support_hourly",
            description="Run customer support pipeline during business hours",
            condition_fn=lambda s: (
                9 <= now().hour <= 17 and
                now().minute < 30  # trigger in first 30 min of any hour
            ),
            action={"type": "run_category", "category": "customer_support"},
            priority=3,
            cooldown_minutes=55,  # ~every hour
        ),
        Rule(
            name="evening_review",
            description="Run analytics and reporting at 6pm daily",
            condition_fn=lambda s: (
                now().hour == 18 and
                not s.get("evening_review_ran", False)
            ),
            action={"type": "run_bot", "bot": "marketing/10_analytics_reporter"},
            priority=3,
            cooldown_minutes=720,
        ),
    ]


# ─── System state builder ─────────────────────────────────────────────────────

def build_system_state(orchestrator, health_registry) -> Dict[str, Any]:
    """Collect current system metrics into a state dict."""
    now = datetime.now()

    # Bot statuses
    all_bots = orchestrator.list_bots()
    bot_statuses = {}
    failed_bots = []
    consecutive_failures = []
    last_run_times = []

    for name in all_bots:
        bot = orchestrator.bots.get(name)
        if not bot:
            continue
        status = bot.get_status()
        bot_statuses[name] = status.get("status", "idle")
        if status.get("status") == "error":
            failed_bots.append(name)
        if status.get("last_run"):
            try:
                last_run_times.append(datetime.fromisoformat(status["last_run"]))
            except Exception:
                pass

    # Health data
    summary = health_registry.get_summary()
    for bot_name in health_registry.get_failed_bots():
        rec = health_registry._records.get(bot_name)
        if rec and rec.consecutive_failures >= 2:
            consecutive_failures.append(bot_name)

    # Time since last activity
    hours_since = 999.0
    if last_run_times:
        latest = max(last_run_times)
        hours_since = (now - latest).total_seconds() / 3600

    # Daily flags (rough check)
    today_str = now.strftime("%Y-%m-%d")
    history = orchestrator.run_history
    today_runs = [r["bot"] for r in history if r["timestamp"].startswith(today_str)]

    pipeline_names_ran_today = set(r.split("/")[-1] for r in today_runs)

    return {
        "timestamp": now.isoformat(),
        "hour": now.hour,
        "weekday": now.weekday(),
        "total_bots": len(all_bots),
        "total_failed": len(failed_bots),
        "failed_bots": failed_bots,
        "consecutive_failures": consecutive_failures,
        "hours_since_last_run": hours_since,
        "avg_health_score": summary.get("avg_health_score", 100),
        # Daily flags
        "morning_ran_today": any("morning" in r or "trend" in r or "content" in r for r in today_runs),
        "sales_ran_today": any("cold_email" in r or "sales" in r for r in today_runs),
        "social_ran_today": any("auto_post" in r or "caption" in r for r in today_runs),
        "content_ran_today": any("blog" in r or "content_gen" in r for r in today_runs),
        "weekly_report_ran": any("reporting" in r or "weekly" in r for r in today_runs),
        "evening_review_ran": any("analytics" in r for r in today_runs),
    }


# ─── Decision Engine ──────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Central autonomous decision-maker.
    Runs in background, evaluates rules, triggers bots/pipelines.
    """

    LOG_SIZE = 200

    def __init__(self, orchestrator, pipeline_engine, health_registry, memory=None):
        self.orchestrator = orchestrator
        self.pipeline_engine = pipeline_engine
        self.health_registry = health_registry
        self.memory = memory
        self.rules: List[Rule] = _build_default_rules()
        self.decision_log: deque = deque(maxlen=self.LOG_SIZE)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval_minutes = 10   # check every 10 minutes
        self._ai_assist = os.getenv("DECISION_AI", "false").lower() == "true"

        # Intelligence layer state
        self._alerts_sent: int = 0
        self._last_run_ts: Optional[float] = None
        self._last_market_eval: float = 0.0    # cooldown: 30 min
        self._last_trends_eval: float = 0.0    # cooldown: 2 h
        self._last_health_eval: float = 0.0    # cooldown: 15 min
        self._last_perf_eval:   float = 0.0    # cooldown: 1 h
        self._last_leads_eval:  float = 0.0    # cooldown: 4 h
        self._last_run_summary: Optional[Dict] = None

    # ─── State + analysis ─────────────────────────────────────────────────────

    def get_state(self) -> Dict:
        return build_system_state(self.orchestrator, self.health_registry)

    def analyze(self, state: Optional[Dict] = None) -> List[Dict]:
        """Evaluate all rules against current state. Return list of triggered actions."""
        if state is None:
            state = self.get_state()

        triggered = []
        # Sort by priority
        for rule in sorted(self.rules, key=lambda r: r.priority):
            if rule.evaluate(state):
                triggered.append({
                    "rule": rule.name,
                    "description": rule.description,
                    "action": rule.action,
                    "priority": rule.priority,
                })
                rule.mark_triggered()
                logger.info(f"🧠 Rule triggered: {rule.name} → {rule.action}")

        return triggered

    def execute_action(self, action: Dict) -> Dict:
        """Execute a single action dict."""
        action_type = action.get("type")
        result = {"action": action, "status": "error", "output": None}

        try:
            if action_type == "run_bot":
                bot_name = action["bot"]
                self.orchestrator.run_bot(bot_name)
                result["status"] = "success"
                result["output"] = f"Bot '{bot_name}' executed"

            elif action_type == "run_pipeline":
                pl_name = action["pipeline"]
                out = self.pipeline_engine.run_pipeline(pl_name)
                result["status"] = "success"
                result["output"] = f"Pipeline '{pl_name}' — {out.get('succeeded')}/{out.get('total_bots')} bots"

            elif action_type == "run_category":
                cat = action["category"]
                self.orchestrator.run_category(cat, parallel=True)
                result["status"] = "success"
                result["output"] = f"Category '{cat}' executed"

            elif action_type == "noop":
                result["status"] = "success"
                result["output"] = "No action needed"

        except Exception as e:
            result["status"] = "error"
            result["output"] = str(e)
            logger.error(f"Decision action failed ({action_type}): {e}")

        return result

    def run_cycle(self) -> List[Dict]:
        """
        Single decision cycle:
        1. Build state
        2. Analyze rules
        3. Execute triggered actions
        4. Log decisions
        """
        state = self.get_state()
        triggered = self.analyze(state)

        results = []
        for item in triggered:
            res = self.execute_action(item["action"])
            entry = {
                "ts": datetime.now().isoformat(),
                "rule": item["rule"],
                "description": item["description"],
                "action": item["action"],
                "result": res["status"],
                "output": res.get("output"),
            }
            self.decision_log.appendleft(entry)
            results.append(entry)

            # Save to memory if available
            if self.memory:
                self.memory.save_decision(entry)

        if not triggered:
            logger.debug("Decision cycle complete — no rules triggered")

        return results

    # ─── Intelligence helpers ─────────────────────────────────────────────────

    def _log_intel(
        self,
        decision_type: str,
        name: str,
        description: str,
        result: str,
        output: str = "",
    ) -> Dict:
        """Create a structured decision log entry and persist it."""
        entry: Dict[str, Any] = {
            "ts": datetime.now().isoformat(),
            "type": decision_type,
            "rule": name,
            "description": description,
            "action": {"type": decision_type, "name": name},
            "result": result,
            "output": output,
        }
        self.decision_log.appendleft(entry)
        if self.memory:
            try:
                self.memory.save_decision(entry)
            except Exception:
                pass
        logger.info(f"[DE:{decision_type}] {name} → {result}: {output[:120]}")
        return entry

    def _send_alert(self, title: str, message: str, channels: Optional[List[str]] = None) -> bool:
        """Broadcast an alert through output_automation and increment counter."""
        try:
            from core.output_automation import get_automator
            result = get_automator().send_alert(
                title, message,
                channels=channels or ["slack", "discord", "email"],
            )
            self._alerts_sent += 1
            logger.info(f"Alert sent: {title}")
            return True
        except Exception as e:
            logger.error(f"Alert send failed: {e}")
            return False

    def _send_slack(self, message: str) -> bool:
        """Send a plain Slack message (non-alert)."""
        try:
            from core.output_automation import get_automator
            get_automator().slack.send(message)
            return True
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False

    def _cooldown_ok(self, attr: str, minutes: int) -> bool:
        """Return True if enough time has elapsed since attr timestamp."""
        elapsed = (time.time() - getattr(self, attr, 0.0)) / 60
        if elapsed >= minutes:
            setattr(self, attr, time.time())
            return True
        return False

    # ─── Market Intelligence ──────────────────────────────────────────────────

    def evaluate_market(self) -> List[Dict]:
        """
        Fetch live crypto prices (bitcoin, ethereum).

        Rules:
          IF 24h change >= +5%  → opportunity alert (Slack + Email)
          IF 24h change <= -5%  → warning alert
        Cooldown: 30 minutes per evaluation.
        """
        if not self._cooldown_ok("_last_market_eval", 30):
            return []

        entries = []
        try:
            from core.integrations import get_integrations
            data = get_integrations().get_crypto_prices(["bitcoin", "ethereum"])
            prices = data.get("prices", [])
            if not prices:
                return []

            for coin in prices:
                name    = coin.get("coin", "?")
                price   = coin.get("price_usd", 0)
                change  = float(coin.get("change_24h") or 0)

                if change >= 5.0:
                    msg = (
                        f"{name.upper()} is UP {change:.1f}% in 24h\n"
                        f"Current price: ${price:,.2f}\n\n"
                        f"Consider: content about crypto gains, affiliate opportunities."
                    )
                    self._send_alert(f"📈 Crypto Opportunity: {name.upper()} +{change:.1f}%", msg)
                    entries.append(self._log_intel(
                        "market", f"crypto_surge_{name}",
                        f"{name.upper()} surged {change:.1f}% in 24h",
                        "alert_sent",
                        f"${price:,.2f} (+{change:.1f}%)",
                    ))

                elif change <= -5.0:
                    msg = (
                        f"{name.upper()} is DOWN {abs(change):.1f}% in 24h\n"
                        f"Current price: ${price:,.2f}\n\n"
                        f"Consider: risk content, hedging articles, buy-the-dip analysis."
                    )
                    self._send_alert(
                        f"📉 Crypto Warning: {name.upper()} {change:.1f}%", msg,
                        channels=["slack"],  # warning only to Slack, not email
                    )
                    entries.append(self._log_intel(
                        "market", f"crypto_drop_{name}",
                        f"{name.upper()} dropped {abs(change):.1f}% in 24h",
                        "alert_sent",
                        f"${price:,.2f} ({change:.1f}%)",
                    ))

        except Exception as e:
            logger.error(f"evaluate_market error: {e}")

        return entries

    # ─── Trend Intelligence ───────────────────────────────────────────────────

    def evaluate_trends(self) -> List[Dict]:
        """
        Fetch Google Trends + Reddit entrepreneur posts.

        Rules:
          IF trending topics exist
            → inject topics into context
            → trigger content_machine pipeline
            → store result in memory
            → send Slack summary
        Cooldown: 2 hours (content pipeline is heavy).
        """
        if not self._cooldown_ok("_last_trends_eval", 120):
            return []

        entries = []
        try:
            from core.integrations import get_integrations
            intel = get_integrations().get_content_intelligence()

            trending   = intel.get("trending_now", [])[:8]
            reddit     = intel.get("reddit", [])[:5]
            news       = intel.get("news", [])[:3]

            if not trending and not reddit:
                logger.debug("evaluate_trends: no trends found, skipping pipeline")
                return []

            topics_str  = ", ".join(trending) if trending else "general content"
            reddit_str  = "\n".join(f"• {p['title']}" for p in reddit) if reddit else ""
            news_titles = "\n".join(f"• {a['title']}" for a in news) if news else ""

            # Trigger content pipeline
            pipeline_result = "skipped"
            try:
                out = self.pipeline_engine.run_pipeline("content_machine")
                ok  = out.get("succeeded", 0)
                tot = out.get("total_bots", 0)
                pipeline_result = f"content_machine: {ok}/{tot} bots succeeded"
            except Exception as pe:
                pipeline_result = f"pipeline error: {pe}"
                logger.warning(f"Trend pipeline error: {pe}")

            # Slack summary
            slack_msg = (
                f"📈 *Trend Intelligence Report*\n"
                f"*Trending now:* {topics_str}\n"
            )
            if reddit_str:
                slack_msg += f"\n*Top Reddit discussions:*\n{reddit_str}\n"
            if news_titles:
                slack_msg += f"\n*Business news:*\n{news_titles}\n"
            slack_msg += f"\n*Action taken:* {pipeline_result}"
            self._send_slack(slack_msg)

            # Store in memory
            if self.memory:
                try:
                    self.memory.save(
                        key=f"trend_intel_{datetime.now().strftime('%Y%m%d_%H')}",
                        content=f"Trends: {topics_str}\n\n{reddit_str}",
                        source="decision_engine",
                        tags=["trends", "intelligence", "content"],
                    )
                except Exception:
                    pass

            entries.append(self._log_intel(
                "trend", "content_from_trends",
                f"{len(trending)} trending topics → content pipeline triggered",
                "pipeline_triggered",
                pipeline_result,
            ))

        except Exception as e:
            logger.error(f"evaluate_trends error: {e}")

        return entries

    # ─── System Health ────────────────────────────────────────────────────────

    def evaluate_system_health(self) -> List[Dict]:
        """
        Check for failed bots.

        Rules:
          IF bot.consecutive_failures == 1  → retry once
            IF retry succeeds → log success
            IF retry fails    → log error + send alert
          IF bot.consecutive_failures >= 3  → escalate alert (critical)
        Cooldown: 15 minutes.
        """
        if not self._cooldown_ok("_last_health_eval", 15):
            return []

        entries = []
        try:
            failed = self.health_registry.get_failed_bots()
            if not failed:
                return []

            # Cap retries at 3 bots per cycle to avoid overloading
            for bot_name in failed[:3]:
                rec = self.health_registry._records.get(bot_name)
                if rec is None:
                    continue

                if rec.consecutive_failures == 1:
                    # First failure — retry once
                    try:
                        self.orchestrator.run_bot(bot_name)
                        entries.append(self._log_intel(
                            "system", f"retry_{bot_name}",
                            f"First failure detected — retried {bot_name}",
                            "success",
                            "Retry succeeded",
                        ))
                    except Exception as retry_err:
                        err_msg = str(retry_err)[:200]
                        self._send_alert(
                            f"⚠️ Bot Failed After Retry: {bot_name}",
                            f"Bot `{bot_name}` failed twice.\n\nError: {err_msg}",
                            channels=["slack"],
                        )
                        entries.append(self._log_intel(
                            "system", f"retry_failed_{bot_name}",
                            f"Retry failed for {bot_name}",
                            "error",
                            err_msg,
                        ))

                elif rec.consecutive_failures >= 3:
                    # Multiple failures — escalate
                    last_err = (rec.last_error or "Unknown error")[:200]
                    self._send_alert(
                        f"🚨 Critical Bot Failure: {bot_name}",
                        (
                            f"Bot `{bot_name}` has failed "
                            f"{rec.consecutive_failures} times in a row.\n\n"
                            f"Last error: {last_err}\n\n"
                            f"Manual investigation required."
                        ),
                    )
                    entries.append(self._log_intel(
                        "system", f"escalate_{bot_name}",
                        f"{bot_name} — {rec.consecutive_failures} consecutive failures",
                        "alert_sent",
                        f"Escalated: {last_err[:100]}",
                    ))

        except Exception as e:
            logger.error(f"evaluate_system_health error: {e}")

        return entries

    # ─── Performance-Based Adaptive Decisions ────────────────────────────────

    def evaluate_performance(self) -> List[Dict]:
        """
        Adaptive intelligence layer — reads historical data and adjusts strategy.

        Rules:
          IF topic_score > 60  → prioritize similar content generation
          IF performance declining → trigger fresh content with new topic categories
          IF pipeline success_rate < 50% → send alert + skip that pipeline
        Cooldown: 1 hour.
        """
        if not self._cooldown_ok("_last_perf_eval", 60):
            return []

        entries = []
        try:
            from core.intelligence import get_intelligence
            intel    = get_intelligence()
            strategy = intel.get_strategy()

            if strategy.get("status") != "ready":
                return []

            trend    = strategy.get("trend", "neutral")
            action   = strategy.get("strategy_adjustments", {}).get("action", "")
            top_topics = strategy.get("top_topics", [])

            # Scaling — ramp up best-performing content type
            if action == "scale_current" and top_topics:
                best_topic = top_topics[0]["topic"]
                # Trigger content pipeline with the best topic
                try:
                    from pipelines.content_pipeline import get_content_pipeline
                    cp = get_content_pipeline(
                        memory=self.memory,
                        intelligence=intel,
                    )
                    result = cp.run(topics=[best_topic], top_n=1, publish=True,
                                    publish_platforms=["static"])
                    intel.record_pipeline_run("content_machine", True,
                                              result.get("duration_s", 0))
                    entries.append(self._log_intel(
                        "performance", "scale_top_topic",
                        f"Scaling best topic: {best_topic[:40]} (trend: {trend})",
                        "pipeline_triggered",
                        f"content_pipeline: {result.get('pieces_created',0)} pieces",
                    ))
                except Exception as e:
                    entries.append(self._log_intel(
                        "performance", "scale_failed",
                        f"Scale attempt failed: {best_topic[:40]}",
                        "error", str(e)[:100],
                    ))

            # Pivot — declining performance → try new topic
            elif action == "pivot_strategy":
                self._send_slack(
                    f"⚠️ *Intelligence Alert*\n"
                    f"Content performance is declining (trend: {trend}).\n"
                    f"Recommendations:\n"
                    + "\n".join(f"• {r}" for r in strategy.get("recommendations", []))
                )
                entries.append(self._log_intel(
                    "performance", "pivot_strategy",
                    f"Declining performance detected — alert sent",
                    "alert_sent",
                    f"avg_score: {strategy.get('avg_recent_score', 0)}",
                ))

            # Check pipeline health
            pipeline_stats = intel.get_pipeline_performance()
            for pl_name, stats in pipeline_stats.items():
                if stats.get("runs", 0) >= 3 and stats.get("success_rate", 100) < 50:
                    self._send_alert(
                        f"🚨 Pipeline Underperforming: {pl_name}",
                        f"Success rate: {stats['success_rate']}% over {stats['runs']} runs",
                        channels=["slack"],
                    )
                    entries.append(self._log_intel(
                        "performance", f"pipeline_alert_{pl_name}",
                        f"Pipeline '{pl_name}' below 50% success rate",
                        "alert_sent",
                        f"{stats['success_rate']}% ({stats['runs']} runs)",
                    ))

            # Generate weekly report
            if datetime.now().weekday() == 6 and datetime.now().hour == 20:
                report = intel.generate_improvement_report()
                self._send_slack(f"📊 *Weekly Intelligence Report Generated*\n{report[:800]}")
                entries.append(self._log_intel(
                    "performance", "weekly_report",
                    "Weekly intelligence report generated",
                    "success", "Report saved to outputs/reports/",
                ))

        except Exception as e:
            logger.error(f"evaluate_performance error: {e}")

        return entries

    # ─── Lead Intelligence ────────────────────────────────────────────────────

    def evaluate_leads(self) -> List[Dict]:
        """
        Check lead capture performance and adapt content strategy.

        Rules:
          IF no leads captured today
            → trigger extra content generation with high-performing topic
          IF high-performing topic exists (score > 60)
            → prioritize that topic in content pipeline
          IF leads_today >= 10
            → send Slack celebration + scale similar content

        Cooldown: 4 hours.
        """
        if not self._cooldown_ok("_last_leads_eval", 240):
            return []

        entries = []
        try:
            from core.email_capture import get_email_capture
            from core.intelligence import get_intelligence
            from core.analytics import get_analytics

            cap      = get_email_capture()
            intel    = get_intelligence()
            analytics = get_analytics()

            leads_today    = len(cap.get_leads_today())
            top_topics     = intel.get_strategy().get("top_topics", [])
            best_topic     = top_topics[0]["topic"] if top_topics else None
            best_score     = top_topics[0]["avg_score"] if top_topics else 0

            # Rule: No leads today → trigger extra content generation
            if leads_today == 0:
                logger.info("No leads today — triggering extra content generation")
                try:
                    from pipelines.content_pipeline import get_content_pipeline
                    cp = get_content_pipeline(
                        memory=self.memory,
                        intelligence=intel,
                    )
                    topics = [best_topic] if best_topic else None
                    result = cp.run(
                        topics=topics,
                        top_n=2,
                        publish=True,
                        publish_platforms=["static"],
                    )
                    analytics.track_post_created(best_topic or "auto", result.get("pieces_created", 0))
                    entries.append(self._log_intel(
                        "leads", "no_leads_content_boost",
                        "No leads today — triggered extra content generation",
                        "pipeline_triggered",
                        f"{result.get('pieces_created', 0)} pieces created",
                    ))
                except Exception as e:
                    entries.append(self._log_intel(
                        "leads", "no_leads_content_boost_failed",
                        "No leads today — content trigger failed",
                        "error", str(e)[:100],
                    ))

            # Rule: High-performing topic (score > 60) → scale similar content
            elif best_score > 60 and best_topic:
                logger.info(f"High-performing topic '{best_topic[:40]}' (score {best_score}) — scaling")
                try:
                    from pipelines.content_pipeline import get_content_pipeline
                    cp = get_content_pipeline(memory=self.memory, intelligence=intel)
                    result = cp.run(topics=[best_topic], top_n=1, publish=True, publish_platforms=["static"])
                    analytics.track_post_created(best_topic, result.get("pieces_created", 0))
                    entries.append(self._log_intel(
                        "leads", "scale_top_topic",
                        f"High-performing topic prioritized: '{best_topic[:40]}' (score {best_score})",
                        "pipeline_triggered",
                        f"{result.get('pieces_created', 0)} pieces",
                    ))
                except Exception as e:
                    entries.append(self._log_intel(
                        "leads", "scale_failed",
                        f"Scale of top topic failed: {best_topic[:40]}",
                        "error", str(e)[:100],
                    ))

            # Rule: 10+ leads today → celebrate + keep scaling
            if leads_today >= 10:
                self._send_slack(
                    f"🎉 *Lead Milestone!*\n"
                    f"You've captured {leads_today} leads today!\n"
                    f"Top topic: {best_topic or 'N/A'}\n"
                    f"Keep the momentum going — consider running content_machine."
                )
                entries.append(self._log_intel(
                    "leads", "lead_milestone",
                    f"{leads_today} leads captured today — milestone alert sent",
                    "alert_sent",
                    f"Best topic: {best_topic or 'N/A'}",
                ))

        except Exception as e:
            logger.error(f"evaluate_leads error: {e}")

        return entries

    # ─── Master Run ───────────────────────────────────────────────────────────

    def run(self) -> Dict:
        """
        Full autonomous intelligence cycle.
        Called by the scheduler (every 15 min) and the API endpoint.

        Steps:
          1. evaluate_market()        — react to crypto price changes
          2. evaluate_trends()        — generate content from trending topics
          3. evaluate_system_health() — retry failed bots, escalate alerts
          4. run_cycle()              — fire time/state-based rules

        Returns a structured summary dict.
        """
        start_ts   = time.time()
        start_iso  = datetime.now().isoformat()
        all_entries: List[Dict] = []
        errors: List[str] = []

        for label, fn in [
            ("market",      self.evaluate_market),
            ("trends",      self.evaluate_trends),
            ("health",      self.evaluate_system_health),
            ("performance", self.evaluate_performance),
            ("leads",       self.evaluate_leads),
            ("rules",       self.run_cycle),
        ]:
            try:
                result = fn()
                all_entries.extend(result or [])
            except Exception as e:
                errors.append(f"{label}: {e}")
                logger.error(f"Decision.run() — {label} error: {e}")

        duration = round(time.time() - start_ts, 2)

        summary: Dict[str, Any] = {
            "started_at":          start_iso,
            "completed_at":        datetime.now().isoformat(),
            "duration_s":          duration,
            "total_actions":       len(all_entries),
            "market_actions":      len([e for e in all_entries if e.get("type") == "market"]),
            "trend_actions":       len([e for e in all_entries if e.get("type") == "trend"]),
            "health_actions":      len([e for e in all_entries if e.get("type") == "system"]),
            "performance_actions": len([e for e in all_entries if e.get("type") == "performance"]),
            "lead_actions":        len([e for e in all_entries if e.get("type") == "leads"]),
            "rule_actions":        len([e for e in all_entries
                                        if e.get("type") not in ("market","trend","system","performance","leads")]),
            "alerts_sent":         self._alerts_sent,
            "errors":              errors,
            "decisions":           all_entries,
        }

        self._last_run_ts      = time.time()
        self._last_run_summary = summary

        logger.info(
            f"🧠 Intelligence run complete — "
            f"{summary['total_actions']} actions | "
            f"{summary['alerts_sent']} alerts | "
            f"{len(errors)} errors | "
            f"{duration}s"
        )
        return summary

    # ─── AI-assisted analysis (optional) ──────────────────────────────────────

    def ai_analyze(self, state: Dict) -> Optional[Dict]:
        """
        Ask GPT to analyze the current system state and suggest an action.
        Only used if DECISION_AI=true in .env.
        """
        if not self._ai_assist:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            state_summary = json.dumps({
                k: v for k, v in state.items()
                if k not in ("failed_bots",)
            }, indent=2)

            pipeline_names = list(self.pipeline_engine.pipelines.keys())

            prompt = f"""
You are the AI decision engine for WheellsVerse, a 70-bot automation system.

Current system state:
{state_summary}

Available pipelines: {', '.join(pipeline_names)}

Based on this state, decide the single MOST valuable action to take right now.
Return JSON only:
{{"type": "run_pipeline"|"run_bot"|"run_category"|"noop",
  "target": "<name>",
  "reason": "<brief reason>"}}

Be conservative — only suggest action if clearly needed.
"""
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.2,
            )
            import re
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
            suggestion = json.loads(raw)
            logger.info(f"🧠 AI suggestion: {suggestion}")
            return suggestion
        except Exception as e:
            logger.debug(f"AI analysis skipped: {e}")
            return None

    # ─── Background loop ──────────────────────────────────────────────────────

    def start(self, interval_minutes: int = 10):
        """Start the decision engine in a background thread."""
        self._interval_minutes = interval_minutes
        self._running = True

        def _loop():
            logger.info(f"🧠 Decision engine started (every {interval_minutes}min)")
            while self._running:
                try:
                    results = self.run_cycle()
                    if results:
                        logger.info(f"🧠 {len(results)} actions executed")
                except Exception as e:
                    logger.error(f"Decision cycle error: {e}")
                # Sleep in small increments for responsive shutdown
                for _ in range(interval_minutes * 6):
                    if not self._running:
                        break
                    time.sleep(10)

        self._thread = threading.Thread(target=_loop, daemon=True, name="DecisionEngine")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🧠 Decision engine stopped")

    # ─── Rule management ──────────────────────────────────────────────────────

    def add_rule(self, rule: Rule):
        self.rules.append(rule)

    def enable_rule(self, name: str, enabled: bool):
        for r in self.rules:
            if r.name == name:
                r.enabled = enabled
                return True
        return False

    def get_rules(self) -> List[Dict]:
        return [r.to_dict() for r in sorted(self.rules, key=lambda r: r.priority)]

    def get_log(self, limit: int = 50) -> List[Dict]:
        return list(self.decision_log)[:limit]

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "interval_minutes": self._interval_minutes,
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules if r.enabled),
            "ai_assist": self._ai_assist,
            "total_decisions": sum(r.trigger_count for r in self.rules),
            "recent_decisions": len(self.decision_log),
            # Intelligence layer
            "alerts_sent": self._alerts_sent,
            "last_run": (
                datetime.fromtimestamp(self._last_run_ts).isoformat()
                if self._last_run_ts else None
            ),
            "last_run_summary": self._last_run_summary,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_engine: Optional[DecisionEngine] = None


def get_decision_engine(orchestrator=None, pipeline_engine=None,
                        health_registry=None, memory=None) -> DecisionEngine:
    global _engine
    if _engine is None:
        if any(x is None for x in [orchestrator, pipeline_engine, health_registry]):
            raise ValueError("Must provide orchestrator, pipeline_engine, health_registry on first call")
        _engine = DecisionEngine(orchestrator, pipeline_engine, health_registry, memory)
    return _engine
