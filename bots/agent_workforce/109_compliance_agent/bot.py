#!/usr/bin/env python3
"""
Bot #109 — Compliance & Watchdog Agent
Category: agent_workforce
Purpose: Autonomous compliance monitor and system watchdog. Reviews all published content
         for FTC compliance, platform policy violations, and legal risks. Monitors agent
         health, detects failures, sends alerts. Acts as the safety layer for the entire
         WheellsVerse automation ecosystem. Runs every hour.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a compliance expert and legal risk analyst specializing in digital
marketing, affiliate marketing, financial content, and FTC regulations. You've helped
100+ online businesses stay compliant while maximizing revenue. You know every rule:
FTC disclosure requirements, GDPR, CAN-SPAM, Meta advertising policies, YouTube
community guidelines, SEC regulations for financial content, and platform-specific
terms of service. You identify risks BEFORE they become violations. Your reviews
are precise, actionable, and prioritized by severity. You protect the business
without killing the revenue — you find the compliant path, not just the safe path."""

ROOT = Path(__file__).resolve().parents[3]


class ComplianceAgentBot(BaseBot):

    def __init__(self):
        super().__init__("109_compliance_agent", "agent_workforce")

    def run(self, action: str = "health_check", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "health_check")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "health_check": self._system_health,
            "review": self._content_review,
            "ftc": self._ftc_audit,
            "platform": self._platform_policy_check,
            "financial": self._financial_content_audit,
            "report": self._compliance_report,
        }
        fn = actions.get(action, self._system_health)
        return fn(ts, **kwargs)

    def _get_recent_outputs(self, n: int = 10) -> list:
        """Scan recent output files across all bots."""
        outputs = []
        output_dir = ROOT / "outputs"
        if output_dir.exists():
            files = sorted(output_dir.rglob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[:n]:
                try:
                    outputs.append({"file": str(f.name), "content": f.read_text()[:1500]})
                except Exception:
                    pass
        return outputs

    def _system_health(self, ts: str, **kwargs) -> dict:
        """Check health of all agents and core systems."""
        health = {}

        # Check agent configs
        agent_dir = ROOT / "bots" / "agent_workforce"
        agents = []
        if agent_dir.exists():
            for d in sorted(agent_dir.iterdir()):
                if d.is_dir():
                    config_file = d / "config.json"
                    bot_file = d / "bot.py"
                    agents.append({
                        "name": d.name,
                        "has_config": config_file.exists(),
                        "has_bot": bot_file.exists(),
                        "enabled": json.loads(config_file.read_text()).get("enabled", False)
                        if config_file.exists() else False,
                    })

        # Check core modules
        core_modules = ["base_bot", "facebook", "instagram", "whatsapp",
                        "telegram", "convertkit", "publish_pipeline"]
        core_health = {}
        for mod in core_modules:
            core_file = ROOT / "core" / f"{mod}.py"
            core_health[mod] = "OK" if core_file.exists() else "MISSING"

        # Check .env keys
        import os
        critical_vars = [
            "ANTHROPIC_API_KEY", "FACEBOOK_PAGE_TOKEN", "FACEBOOK_PAGE_ID",
            "INSTAGRAM_ACCOUNT_ID", "WHATSAPP_ACCESS_TOKEN", "TELEGRAM_BOT_TOKEN",
        ]
        env_status = {v: "SET" if os.getenv(v) else "MISSING" for v in critical_vars}

        health = {
            "timestamp": datetime.now().isoformat(),
            "agents": agents,
            "core_modules": core_health,
            "env_vars": env_status,
            "total_agents": len(agents),
            "enabled_agents": sum(1 for a in agents if a["enabled"]),
        }

        # Alert if critical vars missing
        missing = [k for k, v in env_status.items() if v == "MISSING"]
        if missing:
            try:
                from core.telegram import notify
                notify("⚠️ Compliance Alert — Missing ENV vars:\n" + "\n".join(f"- {m}" for m in missing))
            except Exception:
                pass

        path = self.save_output(
            f"# System Health Check — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n```json\n{json.dumps(health, indent=2)}\n```",
            f"health_{ts}.md", ext="md")

        # Send health summary to Telegram
        try:
            from core.telegram import notify
            status = "✅ ALL SYSTEMS OK" if not missing else f"⚠️ {len(missing)} issues found"
            notify(f"🤖 Compliance Agent — Health Check\n{status}\n"
                   f"Agents: {health['enabled_agents']}/{health['total_agents']} enabled\n"
                   f"Core modules: {sum(1 for v in core_health.values() if v == 'OK')}/{len(core_modules)} OK")
        except Exception:
            pass

        return {"file": str(path), "action": "health_check", "health": health}

    def _content_review(self, ts: str, **kwargs) -> dict:
        """Review recent content for compliance issues."""
        outputs = self._get_recent_outputs(5)
        if not outputs:
            return {"file": "", "action": "review", "issues": []}

        content_samples = "\n\n---\n\n".join(
            f"FILE: {o['file']}\n{o['content']}" for o in outputs
        )

        prompt = f"""Review these recent WheellsVerse content pieces for compliance issues:

{content_samples}

Review checklist:
1. FTC DISCLOSURES — Are affiliate links properly disclosed? (#ad, #sponsored, "affiliate link")
2. FINANCIAL CONTENT — Are income claims qualified? ("results may vary", "not financial advice")
3. INCOME CLAIMS — Flag any unqualified income promises ("make $X guaranteed")
4. PLATFORM POLICIES — Anything that might violate Meta/Instagram/Facebook rules?
5. MEDICAL/LEGAL CLAIMS — Any unauthorized professional advice?
6. SPAM INDICATORS — Excessive caps, trigger words that get flagged by algorithms
7. FACTUAL ACCURACY — Obvious false claims or outdated statistics

For each issue found:
- File name
- Exact quote that's problematic
- Risk level: HIGH / MEDIUM / LOW
- Required fix (specific correction)

If all clear: state "COMPLIANT — No issues found" for that category."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Content Review\n\n{result}", f"content_review_{ts}.md", ext="md")

        # Alert on HIGH risk findings
        if "HIGH" in result.upper():
            try:
                from core.telegram import notify
                notify(f"🚨 COMPLIANCE ALERT — High Risk Content Found\nReview: {Path(str(path)).name}\nImmediate action required!")
            except Exception:
                pass

        return {"file": str(path), "action": "review"}

    def _ftc_audit(self, ts: str, **kwargs) -> dict:
        outputs = self._get_recent_outputs(8)
        content_samples = "\n---\n".join(o["content"][:500] for o in outputs) if outputs else "No recent content"

        prompt = f"""Conduct an FTC compliance audit for WheellsVerse affiliate marketing content.

Recent content samples:
{content_samples}

FTC 2024 Compliance Audit:

1. AFFILIATE DISCLOSURE AUDIT
   - Are all affiliate links disclosed at the START of content (not buried at end)?
   - Is disclosure language clear to an average consumer?
   - Platforms checked: Blog, Facebook, Instagram, Email, WhatsApp

2. TESTIMONIALS & RESULTS
   - Any income testimonials without disclaimer?
   - "Results not typical" or equivalent required?
   - Any before/after claims?

3. ENDORSEMENT STANDARDS
   - Does content reflect honest opinions?
   - Are AI-generated content pieces disclosed as such (required by FTC 2023 guidance)?

4. REQUIRED DISCLOSURES TO ADD
   - Provide exact FTC-compliant disclosure language for each content type

5. PRIORITY ACTION LIST
   - Ranked by legal risk, highest first

Output: Compliance scorecard (A-F) per category + action plan."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# FTC Compliance Audit\n\n{result}", f"ftc_audit_{ts}.md", ext="md")
        return {"file": str(path), "action": "ftc"}

    def _platform_policy_check(self, ts: str, **kwargs) -> dict:
        prompt = """Generate a platform policy compliance guide for WheellsVerse automation.

Platforms we use: Facebook, Instagram, WhatsApp Business API, ConvertKit (email)

For each platform, provide:
1. TOP 5 VIOLATIONS most common for AI/affiliate marketers
2. CURRENT POLICY STATUS for our type of content (allowed/restricted/banned)
3. SAFE HARBOR LANGUAGE — exact phrases that keep us compliant
4. RED FLAG WORDS — terms that trigger review or suppression
5. POSTING FREQUENCY LIMITS — max posts/day before flagged as spam
6. AUTOMATION RULES — what can/cannot be automated per ToS
7. APPEAL PROCESS — if we get flagged/banned, what's the recovery path?

Also include:
- How to label AI-generated content (required by most platforms 2024+)
- Crypto/financial content restrictions per platform
- Affiliate link rules (shortened links, direct links, which are banned)"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(f"# Platform Policy Guide\n\n{result}", f"platform_policy_{ts}.md", ext="md")
        return {"file": str(path), "action": "platform"}

    def _financial_content_audit(self, ts: str, **kwargs) -> dict:
        outputs = self._get_recent_outputs(5)
        finance_content = "\n---\n".join(
            o["content"][:600] for o in outputs
            if any(k in o["file"].lower() for k in ["finance", "crypto", "stock", "signal", "defi"])
        ) or "No financial content found in recent outputs"

        prompt = f"""Audit WheellsVerse financial content for legal and regulatory compliance.

Financial content to review:
{finance_content}

SEC/FINRA/FCA Compliance Review:
1. INVESTMENT ADVICE VIOLATIONS
   - Any content that crosses from "education" to "advice" without disclaimer?
   - Specific buy/sell recommendations without proper licensing disclaimer?

2. REQUIRED DISCLAIMERS
   - "Not financial advice" — present and visible?
   - "Past performance doesn't guarantee future results"
   - "Cryptocurrency is highly volatile and speculative"
   - "This is for educational purposes only"

3. CRYPTO-SPECIFIC RISKS
   - Pump-and-dump promotion risk (naming specific coins + price targets)
   - ICO/token promotion without securities exemption notice
   - Unregistered investment advisor issues

4. AFFILIATE DISCLOSURE FOR FINANCIAL PRODUCTS
   - Coinbase / Robinhood / Binance affiliate links — properly disclosed?

5. COMPLIANT REWRITE
   - Provide a compliant version of any flagged passage

Risk rating: LOW / MEDIUM / HIGH / CRITICAL"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Financial Content Audit\n\n{result}", f"financial_audit_{ts}.md", ext="md")

        if "CRITICAL" in result.upper() or "HIGH" in result.upper():
            try:
                from core.telegram import notify
                notify(f"🚨 COMPLIANCE — Financial Content Risk\nCritical or High risk findings in financial content.\n📁 {Path(str(path)).name}")
            except Exception:
                pass

        return {"file": str(path), "action": "financial"}

    def _compliance_report(self, ts: str, **kwargs) -> dict:
        """Generate full weekly compliance report."""
        today = datetime.now().strftime("%B %d, %Y")
        outputs = self._get_recent_outputs(15)
        recent_files = [o["file"] for o in outputs]

        prompt = f"""Generate the WheellsVerse Weekly Compliance Report for {today}.

Recent content files reviewed: {', '.join(recent_files) or 'None'}

Weekly Compliance Report:

EXECUTIVE SUMMARY
- Overall compliance health score (A-F)
- Top 3 risks identified this week
- Actions taken / pending

FTC STATUS — Affiliate Marketing
- Disclosure compliance rate
- Required improvements

FINANCIAL CONTENT STATUS
- Disclaimer compliance
- Risk level of published content

PLATFORM POLICY STATUS
- Facebook compliance
- Instagram compliance
- WhatsApp compliance
- Email (CAN-SPAM) compliance

AUTOMATION COMPLIANCE
- Posting frequency — within limits?
- API usage — within rate limits?
- Content detection risk

ACTION ITEMS (Ranked by priority):
1. [CRITICAL] ...
2. [HIGH] ...
3. [MEDIUM] ...

NEXT WEEK FOCUS:
- What to monitor and improve

Format as professional legal compliance memo."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(
            f"# Compliance Report — {today}\n\n{result}",
            f"compliance_report_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            lines = result.split("\n")[:8]
            notify("📋 Compliance Agent — Weekly Report\n" + "\n".join(lines) + "\n\n📁 Full report saved.")
        except Exception:
            pass

        return {"file": str(path), "action": "report"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compliance & Watchdog Agent")
    parser.add_argument("--action", default="health_check",
                        choices=["health_check", "review", "ftc", "platform", "financial", "report"])
    args = parser.parse_args()
    bot = ComplianceAgentBot()
    result = bot.execute(action=args.action)
    print(f"\n✅ Compliance Agent: {result.get('file', 'completed')}")
