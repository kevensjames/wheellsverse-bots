#!/usr/bin/env python3
"""
Bot #103 — CEO Agent
Category: agent_workforce
Purpose: Autonomous CEO that searches profitable niches, builds business strategies,
         coordinates all other agents, finds revenue opportunities, tracks KPIs,
         and acts as the strategic brain of WheellsVerse. Runs every 6 hours.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an autonomous AI CEO running WheellsVerse — a profitable AI automation
and digital products business. You think like a ruthless, data-driven entrepreneur.
Your job: find the highest-ROI opportunities, build strategies to execute them,
coordinate the agent workforce, and maximize revenue. You are direct, specific,
and action-oriented. No fluff — only executable plans with clear revenue projections.
You understand digital products, affiliate marketing, SaaS, content monetization,
crypto, and passive income. Think like Elon Musk meets Warren Buffett meets a
top growth hacker."""


class CEOAgentBot(BaseBot):

    def __init__(self):
        super().__init__("103_ceo_agent", "agent_workforce")

    def run(self, action: str = "strategy", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "strategy")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "strategy": self._daily_strategy,
            "niche_hunt": self._niche_hunt,
            "revenue": self._revenue_plan,
            "brief": self._agent_brief,
            "kpis": self._kpi_report,
            "opportunity": self._opportunity_scan,
        }
        fn = actions.get(action, self._daily_strategy)
        return fn(ts, **kwargs)

    def _daily_strategy(self, ts: str, **kwargs) -> dict:
        # Get current date context
        today = datetime.now().strftime("%A, %B %d, %Y")

        # Try to get real internet data for context
        trends = []
        try:

            internet = getattr(self, '_web', None)
            if not internet:
                from bots.narai.narai.bot import NarAIInternet
                internet = NarAIInternet()
            results = internet.search("best AI business opportunities 2026 passive income", num=3)
            trends = [r.get("title", "") for r in results if r.get("title")]
        except Exception:
            pass

        trend_context = "\n".join(f"- {t}" for t in trends) if trends else "- AI automation growing 40% YoY\n- Creator economy at $250B\n- DeFi yields averaging 8-15%"

        prompt = f"""Today is {today}. You are the CEO of WheellsVerse.

Current market signals:
{trend_context}

WheellsVerse assets:
- 113 AI bots running 24/7
- NEXORA creator platform (in development)
- Facebook + Instagram publishing pipeline
- WhatsApp business channel
- Stripe payment system
- ConvertKit email list
- Affiliate partnerships: Coinbase, Robinhood, Amazon

Generate today's CEO strategy briefing:

1. TOP 3 REVENUE MOVES THIS WEEK (specific, executable, with $ estimate)
2. AGENT ASSIGNMENTS (which bot should do what today)
3. BOTTLENECK IDENTIFIED (what's blocking most revenue right now)
4. ONE BIG BET (highest upside opportunity to pursue this month)
5. METRICS TO WATCH (3 KPIs that matter most right now)

Be ruthlessly specific. No generic advice."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# CEO Daily Strategy — {today}\n\n{result}",
                                f"ceo_strategy_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            # Send brief summary to Telegram
            lines = result.split("\n")
            preview = "\n".join(lines[:8])
            notify(f"🧠 CEO Daily Brief\n{preview}\n\n📁 Full report saved.")
        except Exception:
            pass

        return {"file": str(path), "action": "strategy"}

    def _niche_hunt(self, ts: str, **kwargs) -> dict:
        prompt = """As CEO of WheellsVerse, hunt for the top 10 most profitable digital niches right now.

For each niche provide:
- Niche name
- Why it's hot right now (data/signal)
- Revenue model (how we make money)
- Time to first $1K (realistic)
- Competition level (low/medium/high)
- Best platform to dominate it
- First action to take TODAY

Focus on niches where AI automation gives us a massive unfair advantage.
Prioritize: high margin, low competition, fast payoff.

Output as structured list, ranked by profit potential."""

        try:
            from bots.narai.narai.bot import NarAIInternet
            internet = NarAIInternet()
            news = internet.news("profitable online business niche 2026", num=5)
            context = "\n".join(f"- {n.get('title', '')} ({n.get('source', '')})" for n in news)
            prompt += f"\n\nLatest market signals:\n{context}"
        except Exception:
            pass

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(f"# Niche Hunt Report\n\n{result}", f"niche_hunt_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🔍 CEO Niche Hunt Complete\n📊 10 niches analyzed\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "niche_hunt"}

    def _revenue_plan(self, ts: str, **kwargs) -> dict:
        target = kwargs.get("target", "$10,000/month")
        prompt = f"""Build a detailed revenue plan to hit {target} with WheellsVerse.

Current revenue streams available:
- Affiliate commissions (Coinbase, Robinhood, Amazon)
- Digital product sales (Bot Pack $97, Pro $29/mo)
- NEXORA creator platform (subscription revenue share)
- AI content agency services
- Crypto/finance signal newsletter

For each revenue stream:
1. Current potential (honest estimate)
2. Actions needed to unlock it (specific steps)
3. Timeline to meaningful revenue
4. Who/what executes it (which agent)

Then: THE MASTER PLAN — integrated 90-day roadmap to {target}
Include: daily, weekly, monthly milestones with revenue targets."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(f"# Revenue Plan: {target}\n\n{result}",
                                f"revenue_plan_{ts}.md", ext="md")
        return {"file": str(path), "action": "revenue", "target": target}

    def _agent_brief(self, ts: str, **kwargs) -> dict:
        # Get list of all running agents
        try:
            from core.orchestrator import get_orchestrator
            orch = get_orchestrator()
            agent_list = "\n".join(f"- {k}: {v.get('description', '')}"
                                    for k, v in orch.registry.items())
        except Exception:
            agent_list = "- All 113 bots available"

        prompt = f"""As CEO, create today's task brief for the agent workforce.

Available agents:
{agent_list}

Assign specific tasks to each agent for maximum revenue impact today.
For each assignment:
- Agent name
- Specific task (not vague)
- Expected output
- Priority (1-5)
- Why this task makes money

Focus on: content that drives affiliate clicks, NEXORA growth, product sales."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Agent Brief — {datetime.now().strftime('%Y-%m-%d')}\n\n{result}",
                                f"agent_brief_{ts}.md", ext="md")
        return {"file": str(path), "action": "brief"}

    def _kpi_report(self, ts: str, **kwargs) -> dict:
        # Try to gather real data
        data_dir = Path(__file__).resolve().parents[3] / "data"
        kpi_data = {}
        for fname in ["bot_health.json", "token_usage.json", "click_tracker.json"]:
            fp = data_dir / fname
            if fp.exists():
                try:
                    kpi_data[fname] = json.loads(fp.read_text())
                except Exception:
                    pass

        prompt = f"""As CEO, generate a KPI report for WheellsVerse.

Available data: {json.dumps(kpi_data, indent=2)[:2000] if kpi_data else 'No data files found yet'}

Generate the KPI dashboard covering:
1. Revenue KPIs (actual or projected)
2. Traffic & engagement metrics
3. Bot performance (content published, platforms hit)
4. Growth metrics (followers, email list, leads)
5. Key red flags to address
6. CEO verdict: are we on track?

Be honest. If data is missing, say what needs to be tracked and how."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(f"# KPI Report — {datetime.now().strftime('%Y-%m-%d')}\n\n{result}",
                                f"kpi_report_{ts}.md", ext="md")
        return {"file": str(path), "action": "kpis"}

    def _opportunity_scan(self, ts: str, **kwargs) -> dict:
        prompt = """Scan for immediate money-making opportunities for WheellsVerse RIGHT NOW.

Look for:
1. Trending topics we can create content about + monetize (affiliate angle)
2. Products/services we can launch in under 48 hours
3. Partnerships or collaborations that would pay fast
4. Underserved audiences we could capture immediately
5. Arbitrage opportunities (buy low, sell high in digital space)

For each opportunity:
- What it is
- How fast we can execute (hours/days)
- Revenue potential in 30 days
- Exactly what to build/do first

Be aggressive and creative. We have 113 bots — use them."""

        try:
            from bots.narai.narai.bot import NarAIInternet
            internet = NarAIInternet()
            results = internet.search("viral AI money making opportunity 2026", num=5)
            context = "\n".join(f"- {r.get('title', '')} — {r.get('snippet', '')[:100]}" for r in results)
            prompt += f"\n\nLive internet signals:\n{context}"
        except Exception:
            pass

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Opportunity Scan\n\n{result}", f"opportunity_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            lines = result.split("\n")
            preview = "\n".join(lines[:6])
            notify(f"💡 CEO Opportunity Scan\n{preview}")
        except Exception:
            pass

        return {"file": str(path), "action": "opportunity"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CEO Agent")
    parser.add_argument("--action", default="strategy",
                        choices=["strategy", "niche_hunt", "revenue", "brief", "kpis", "opportunity"])
    parser.add_argument("--target", type=str, default="$10,000/month")
    args = parser.parse_args()
    bot = CEOAgentBot()
    result = bot.execute(action=args.action, target=args.target)
    print(f"\n✅ CEO Agent: {result['file']}")
