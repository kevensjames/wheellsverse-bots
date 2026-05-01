#!/usr/bin/env python3
"""
core/superagent.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse SuperAgent — Autonomous Revenue Intelligence

Oversees all 70+ bots, creates new ones on demand, and maximizes daily
affiliate revenue across Amazon, Robinhood, Coinbase, and every program.

Cycle (runs every 2 hours, or on demand):
  1. Assess  — bot statuses, revenue data, content output quality
  2. Plan    — GPT-4 reasons about what to run / create / optimize
  3. Execute — runs bots, writes + deploys new bot code, builds pipelines
  4. Log     — every decision stored with reasoning for the dashboard
─────────────────────────────────────────────────────────────────────────────
"""

import concurrent.futures
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("superagent")

# ─── Bot code template ────────────────────────────────────────────────────────

_BOT_TEMPLATE = '''\
#!/usr/bin/env python3
"""
{bot_path}
SuperAgent-created bot — {description}
Revenue goal: {goal}
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot


class {class_name}(BaseBot):
    """{description}"""

    def __init__(self):
        super().__init__("{bot_name}", "{category}")

    def run(self, topic: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic", "{default_topic}")
        self.logger.info(f"Running {{self.name}}: {{topic}}")

{run_body}

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = self.save_output(output, f"{{self.name}}_{{ts}}.md", ext="md")
        self.logger.info(f"Saved: {{path}}")
        return {{"file": str(path), "topic": topic, "bot": self.name}}


if __name__ == "__main__":
    bot = {class_name}()
    result = bot.execute()
    print(f"Output: {{result['file']}}")
'''

# ─── SuperAgent ───────────────────────────────────────────────────────────────


class SuperAgent:
    """
    Autonomous revenue agent that controls the entire WheellsVerse ecosystem.
    Creates new bots, runs existing ones, and optimizes for maximum daily income.
    """

    VERSION = "2.0"
    MAX_PARALLEL_BOTS = 8          # max bots running at the same time

    # Revenue bots the agent focuses on running
    CORE_REVENUE_SEQUENCE = [
        "marketing/01_content_generator",
        "marketing/02_seo_optimizer",
        "marketing/07_keyword_scraper",
        "marketing/16_blog_publisher",
        "social_media/37_auto_post",
        "social_media/38_content_scheduler",
        "social_media/45_multi_platform_poster",
        "marketing/03_email_campaign",
        "ecommerce/61_product_description",
    ]

    def __init__(self, orchestrator=None):
        from core.orchestrator import get_orchestrator
        self.orch = orchestrator or get_orchestrator()
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

        self.status = "idle"           # idle | running | stopped
        self.cycle_count = 0
        self.daily_revenue_goal = 10.0  # USD — grows as earnings increase
        self.revenue_today = 0.0
        self.created_bots: List[Dict] = []
        self.decision_log: List[Dict] = []
        self._auto_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Persist created bots across restarts
        self._meta_path = ROOT / "data" / "superagent_meta.json"
        self._load_meta()

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load_meta(self):
        if self._meta_path.exists():
            try:
                data = json.loads(self._meta_path.read_text())
                self.created_bots = data.get("created_bots", [])
                self.cycle_count = data.get("cycle_count", 0)
                self.daily_revenue_goal = data.get("daily_revenue_goal", 10.0)
            except Exception:
                pass

    def _save_meta(self):
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        self._meta_path.write_text(json.dumps({
            "created_bots": self.created_bots,
            "cycle_count": self.cycle_count,
            "daily_revenue_goal": self.daily_revenue_goal,
            "last_cycle": datetime.now().isoformat(),
        }, indent=2))

    def _log(self, action: str, reason: str, result: str = "", level: str = "INFO"):
        entry = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "action": action,
            "reason": reason,
            "result": result,
            "level": level,
        }
        self.decision_log.append(entry)
        if len(self.decision_log) > 200:
            self.decision_log = self.decision_log[-200:]
        getattr(logger, level.lower(), logger.info)(f"[{action}] {reason}")

    # ─── Assessment ───────────────────────────────────────────────────────────

    def assess(self) -> Dict:
        """Gather full system state for GPT-4 to reason about."""
        from core.impact import get_earnings

        earnings_7d = get_earnings(days=7)
        earnings_1d = get_earnings(days=1)

        # Bot statuses
        bot_states: Dict[str, str] = {}
        run_counts: Dict[str, int] = {}
        for key, bot in self.orch.bots.items():
            s = bot.get_status()
            bot_states[key] = s.get("status", "idle")
            run_counts[key] = s.get("run_count", 0)

        # Recent outputs
        outputs_dir = ROOT / "outputs"
        recent_files: List[str] = []
        if outputs_dir.exists():
            all_files = sorted(
                [f for f in outputs_dir.rglob("*.md")],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            recent_files = [str(f.relative_to(ROOT)) for f in all_files[:10]]

        # Today's bot runs
        running_now = [k for k, s in bot_states.items() if s == "running"]
        done_today = [k for k, s in bot_states.items() if s == "done"]
        errors = [k for k, s in bot_states.items() if s == "error"]

        revenue_7d = earnings_7d.get("total_earned", 0.0)
        revenue_1d = earnings_1d.get("total_earned", 0.0)
        self.revenue_today = revenue_1d

        # Raise goal as earnings grow
        if revenue_7d > 50:
            self.daily_revenue_goal = max(self.daily_revenue_goal, 25.0)
        elif revenue_7d > 10:
            self.daily_revenue_goal = max(self.daily_revenue_goal, 15.0)

        # Full bot roster — passed to planner so GPT-4 only uses real names
        all_bot_names = sorted(self.orch.bots.keys())

        return {
            "timestamp": datetime.now().isoformat(),
            "revenue_today": round(revenue_1d, 2),
            "revenue_7d": round(revenue_7d, 2),
            "daily_goal": self.daily_revenue_goal,
            "goal_met": revenue_1d >= self.daily_revenue_goal,
            "top_programs": earnings_7d.get("by_program", {}),
            "running_bots": running_now,
            "done_today": done_today,
            "error_bots": errors,
            "total_bots": len(self.orch.bots),
            "all_bot_names": all_bot_names,
            "recent_outputs": recent_files,
            "created_bots_count": len(self.created_bots),
            "amazon_tag": os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20"),
            "hour_of_day": datetime.now().hour,
            "affiliate_programs": {
                "amazon": os.getenv("AFFILIATE_AMAZON_TAG", ""),
                "coinbase": os.getenv("AFFILIATE_COINBASE_URL", ""),
                "webull": os.getenv("AFFILIATE_WEBULL_URL", ""),
                "convertkit": os.getenv("AFFILIATE_CONVERTKIT_URL", ""),
                "fiverr": os.getenv("AFFILIATE_FIVERR_URL", ""),
            },
        }

    # ─── Planning ─────────────────────────────────────────────────────────────

    def plan(self, assessment: Dict) -> Dict:
        """
        Use GPT-4 to decide what actions to take to maximize revenue.
        Returns a structured action plan.
        """
        rev = assessment["revenue_today"]
        goal = assessment["daily_goal"]
        done = assessment["done_today"]
        programs = assessment["affiliate_programs"]
        all_bots = assessment.get("all_bot_names", list(self.orch.bots.keys()))
        # Revenue-focused bots to highlight
        revenue_bots = [b for b in all_bots if any(
            kw in b for kw in ["content", "seo", "blog", "social", "post",
                                "email", "funnel", "landing", "keyword", "affiliate",
                                "product", "copywriter", "auto_post", "scheduler"]
        )]

        system = (
            "You are the WheellsVerse SuperAgent — an autonomous AI revenue strategist. "
            "Your ONE goal: maximize daily affiliate income for Jhon Wheeler (J.K. Blaze). "
            "You control 70+ bots and can create new ones. "
            "Be decisive, revenue-focused, and action-oriented. "
            "CRITICAL: Only reference bot names that exist in the AVAILABLE BOTS list. "
            "Return ONLY valid JSON — no markdown, no explanation outside the JSON."
        )

        # Pre-compute max bot number (backslashes not allowed inside f-string expressions on Python < 3.12)
        _bot_num_pat = re.compile(r'^(\d+)')
        _max_bot_num = max(
            (int(m.group(1)) for b in all_bots for m in [_bot_num_pat.match(b.split('/')[-1])] if m),
            default=70
        ) if all_bots else 70

        prompt = f"""Current system state:
- Time: {datetime.now().strftime('%A %H:%M')}
- Revenue today: ${rev:.2f} (goal: ${goal:.2f})
- Goal met: {assessment['goal_met']}
- Bots completed today: {len(done)} ({', '.join(done[:5]) if done else 'none'})
- Bots running now: {assessment['running_bots'] or 'none'}
- Error bots: {assessment['error_bots'][:3] if assessment['error_bots'] else 'none'}
- Content files generated: {len(assessment['recent_outputs'])}
- SuperAgent-created bots so far: {assessment['created_bots_count']}

AVAILABLE BOTS (use ONLY these exact strings for run_bot/run_sequence targets):
{chr(10).join(f'  {b}' for b in all_bots)}

Revenue-focused bots (prioritize these):
{chr(10).join(f'  {b}' for b in revenue_bots[:20])}

Affiliate link context:
- Amazon tag: {programs['amazon']} (commissions on ANY purchase after click)
- Coinbase: {programs['coinbase']} ($10 per signup + fee share)
- Robinhood: {programs['webull']} ($20 per funded account)
- ConvertKit: {programs['convertkit']} (30% recurring)

Return a JSON action plan:
{{
  "analysis": "1-2 sentence assessment of current state",
  "priority": "content|social|email|create_bot|upgrade|optimize",
  "actions": [
    {{
      "type": "run_parallel",
      "targets": ["exact_bot_1", "exact_bot_2", "exact_bot_3", "...up to 8"],
      "reason": "why running these together maximizes revenue"
    }},
    {{
      "type": "run_bot",
      "target": "EXACT name from AVAILABLE BOTS list above",
      "kwargs": {{}},
      "reason": "why this helps revenue"
    }},
    {{
      "type": "upgrade_bot",
      "target": "exact/bot_name",
      "improvement": "what to improve — e.g. better affiliate links, smarter prompts"
    }},
    {{
      "type": "create_bot",
      "name": "73_slug_name",
      "category": "specialized|marketing|ecommerce|social_media",
      "description": "What it does",
      "goal": "Revenue goal",
      "default_topic": "Default topic",
      "affiliate_focus": "amazon|coinbase|robinhood|all"
    }}
  ],
  "daily_message": "Motivational summary of today's revenue strategy"
}}

STRICT RULES:
- All bot names MUST be copied exactly from the AVAILABLE BOTS list — no inventing names
- Include 4-8 actions per cycle — more parallel work = more revenue
- ALWAYS include at least one run_parallel action with 4-8 revenue-focused bots
- Prefer run_parallel over run_bot — run many at once
- Create a new bot only if revenue is $0 AND fewer than 5 SuperAgent bots exist
- Upgrade a bot if it has run multiple times but revenue is flat
- New bot names must use next available number (current highest: {_max_bot_num})
- High-value niches: AI tools, crypto, stock investing, passive income, side hustles"""

        try:
            from core.llm_client import safe_openai_call
            resp = safe_openai_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                max_tokens=1200,
                temperature=0.7,
                response_format={"type": "json_object"},
                bot_name="superagent.plan",
            )
            plan = json.loads(resp.choices[0].message.content)
            return plan
        except Exception as e:
            logger.error(f"Plan generation failed: {e}")
            return self._fallback_plan(assessment)

    def _fallback_plan(self, assessment: Dict) -> Dict:
        """Safe default plan when GPT-4 is unavailable."""
        done = set(assessment.get("done_today", []))
        targets = [b for b in self.CORE_REVENUE_SEQUENCE if b not in done][:3]
        return {
            "analysis": "Running core revenue sequence (GPT-4 offline).",
            "priority": "content",
            "actions": [{"type": "run_sequence", "targets": targets,
                         "reason": "Core daily revenue bots"}],
            "daily_message": "Running core bots to generate affiliate content.",
        }

    # ─── Execution ────────────────────────────────────────────────────────────

    def execute(self, plan: Dict) -> List[str]:
        """Execute the planned actions. Returns list of result summaries."""
        results = []
        actions = plan.get("actions", [])

        self._log(
            "PLAN",
            plan.get("analysis", ""),
            f"Priority: {plan.get('priority')} | {len(actions)} actions | "
            f"{plan.get('daily_message', '')}",
        )

        for action in actions:
            atype = action.get("type", "")
            try:
                if atype == "run_bot":
                    r = self._action_run_bot(action)
                elif atype in ("run_sequence", "run_parallel"):
                    r = self._action_run_parallel(action)
                elif atype == "create_bot":
                    r = self._action_create_bot(action)
                elif atype == "upgrade_bot":
                    r = self._action_upgrade_bot(action)
                else:
                    r = f"Unknown action type: {atype}"
                results.append(r)
            except Exception as e:
                err = f"Action {atype} failed: {e}"
                logger.error(err)
                self._log("ERROR", err, level="ERROR")
                results.append(err)

        return results

    def _action_run_bot(self, action: Dict) -> str:
        target = action.get("target", "")
        kwargs = action.get("kwargs", {})
        reason = action.get("reason", "")

        if target not in self.orch.bots:
            msg = f"Bot not found: {target}"
            self._log("SKIP", msg, reason, level="WARN")
            return msg

        self._log("RUN_BOT", f"Running {target}", reason)
        try:
            def _bg():
                self.orch.run_bot(target, **kwargs)
            t = threading.Thread(target=_bg, daemon=True)
            t.start()
            return f"Started {target}"
        except Exception as e:
            self._log("ERROR", f"Failed to start {target}: {e}", level="ERROR")
            return f"Error: {e}"

    def _action_run_parallel(self, action: Dict) -> str:
        """Launch up to MAX_PARALLEL_BOTS bots simultaneously."""
        targets = action.get("targets", [])
        reason = action.get("reason", "")
        valid = [t for t in targets if t in self.orch.bots]
        skipped = [t for t in targets if t not in self.orch.bots]

        for t in skipped:
            self._log("SKIP", f"Bot not found: {t}", level="WARN")

        if not valid:
            return "No valid bots to run"

        self._log("RUN_PARALLEL", f"Launching {len(valid)} bots in parallel", reason)

        def _run(key: str):
            try:
                self.orch.run_bot(key)
            except Exception as e:
                logger.error(f"Parallel bot {key} failed: {e}")

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_PARALLEL_BOTS)
        for key in valid:
            executor.submit(_run, key)
        executor.shutdown(wait=False)

        return f"Started {len(valid)} bots in parallel: {valid}"

    def _action_upgrade_bot(self, action: Dict) -> str:
        """Read an existing bot, ask GPT-4 to improve it, save + hot-reload."""
        target = action.get("target", "")
        improvement = action.get("improvement",
                                 "improve revenue generation and affiliate link placement")

        if target not in self.orch.bots:
            return f"Bot not found: {target}"

        parts = target.split("/", 1)
        if len(parts) != 2:
            return f"Invalid bot key: {target}"
        category, name = parts
        bot_py = ROOT / "bots" / category / name / "bot.py"

        if not bot_py.exists():
            return f"Bot file not found: {bot_py}"

        current_code = bot_py.read_text(encoding="utf-8")
        self._log("UPGRADE_BOT", f"Upgrading {target}", improvement)

        try:
            from core.llm_client import safe_openai_call
            resp = safe_openai_call(
                messages=[
                    {"role": "system", "content": (
                        "You are an expert Python developer improving affiliate revenue bots. "
                        "Rewrite the bot code based on the improvement request. "
                        "Return ONLY the complete improved Python file — no markdown fences, "
                        "no explanation. Keep the same class name and structure."
                    )},
                    {"role": "user", "content":
                        f"Improvement: {improvement}\n\nCurrent code:\n{current_code}"},
                ],
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                max_tokens=2000,
                temperature=0.3,
                bot_name="superagent.upgrade",
            )
            new_code = resp.choices[0].message.content.strip()
            new_code = re.sub(r"^```python\s*", "", new_code)
            new_code = re.sub(r"\s*```$", "", new_code)

            compile(new_code, str(bot_py), "exec")          # syntax check

            # Backup original, save improved version
            bot_py.with_suffix(".py.bak").write_text(current_code, encoding="utf-8")
            bot_py.write_text(new_code, encoding="utf-8")

            # Hot-reload
            cfg_path = bot_py.parent / "config.json"
            config = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
            self.orch._load_single_bot(
                bot_py=bot_py, bot_name=name, category=category, config=config
            )
            self._log("UPGRADED_BOT", f"Upgraded + reloaded {target}", improvement)
            return f"Upgraded + reloaded: {target}"

        except SyntaxError as e:
            return f"Syntax error in upgraded code: {e}"
        except Exception as e:
            self._log("ERROR", f"Upgrade {target} failed: {e}", level="ERROR")
            return f"Upgrade failed: {e}"

    # ─── Bot Creation ─────────────────────────────────────────────────────────

    def _action_create_bot(self, action: Dict) -> str:
        name = action.get("name", "")
        category = action.get("category", "specialized")
        description = action.get("description", "")
        goal = action.get("goal", "Generate affiliate revenue")
        default_topic = action.get("default_topic", "AI tools for making money")
        affiliate_focus = action.get("affiliate_focus", "all")

        # Sanitize name
        name = re.sub(r"[^a-z0-9_]", "_", name.lower())
        if not name:
            return "Bot creation skipped: no name provided"

        # Don't recreate existing
        full_key = f"{category}/{name}"
        if full_key in self.orch.bots:
            self._log("SKIP", f"Bot {full_key} already exists")
            return f"Bot {full_key} already exists"

        self._log("CREATE_BOT", f"Creating {full_key}", f"{description} | {goal}")

        try:
            code = self._generate_bot_code(
                name=name,
                category=category,
                description=description,
                goal=goal,
                default_topic=default_topic,
                affiliate_focus=affiliate_focus,
            )
        except Exception as e:
            self._log("ERROR", f"Code generation failed for {name}: {e}", level="ERROR")
            return f"Code gen failed: {e}"

        # Validate syntax
        try:
            compile(code, f"bots/{category}/{name}/bot.py", "exec")
        except SyntaxError as e:
            self._log("ERROR", f"Syntax error in generated code: {e}", level="ERROR")
            return f"Syntax error: {e}"

        # Save to disk
        bot_dir = ROOT / "bots" / category / name
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "bot.py").write_text(code, encoding="utf-8")
        (bot_dir / "config.json").write_text(json.dumps({
            "description": description,
            "goal": goal,
            "default_topic": default_topic,
            "affiliate_focus": affiliate_focus,
            "created_by": "SuperAgent",
            "created_at": datetime.now().isoformat(),
            "schedule": "@daily 09:00",
            "enabled": True,
        }, indent=2), encoding="utf-8")

        # Hot-register with orchestrator
        try:
            self.orch._load_single_bot(
                bot_py=bot_dir / "bot.py",
                bot_name=name,
                category=category,
                config=json.loads((bot_dir / "config.json").read_text()),
            )
            registered = True
        except Exception as e:
            logger.warning(f"Hot-register failed ({e}), will load on next restart")
            registered = False

        record = {
            "full_name": full_key,
            "name": name,
            "category": category,
            "description": description,
            "goal": goal,
            "created_at": datetime.now().isoformat(),
            "registered": registered,
        }
        self.created_bots.append(record)
        self._save_meta()

        # Run it immediately
        if registered and full_key in self.orch.bots:
            def _run():
                time.sleep(2)
                self.orch.run_bot(full_key)
            threading.Thread(target=_run, daemon=True).start()
            self._log("RUN_BOT", f"Auto-running new bot {full_key}", "First run after creation")

        result_msg = f"Created + {'registered' if registered else 'saved (restart to load)'}: {full_key}"
        self._log("CREATED_BOT", result_msg, description)
        return result_msg

    def _generate_bot_code(
        self,
        name: str,
        category: str,
        description: str,
        goal: str,
        default_topic: str,
        affiliate_focus: str,
    ) -> str:
        """Use GPT-4 to write the bot's run() body, then wrap it in the template."""
        amazon_tag = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
        coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "")
        robinhood_url = os.getenv("AFFILIATE_WEBULL_URL", "")

        affiliate_context = f"""
Available affiliate links to embed naturally in generated content:
- Amazon Associates tag: {amazon_tag}
  Use as: https://www.amazon.com/s?k=PRODUCT&tag={amazon_tag}
- Coinbase: {coinbase_url}
- Robinhood: {robinhood_url}
"""

        system = (
            "You are an expert Python developer building affiliate revenue bots. "
            "Generate ONLY the indented body of a run() method for a Python bot class. "
            "The method must produce an `output` string (markdown) and nothing else at the end. "
            "Use self.ai(prompt, system=system_str, max_tokens=2000) for GPT calls. "
            "Do NOT include the def run(...) line, class definition, imports, or any code after `output = ...`. "
            "The last assignment must be: output = ... (a string). "
            "Indent everything with 8 spaces (inside run() inside class)."
        )

        prompt = f"""Bot name: {name}
Description: {description}
Revenue goal: {goal}
Default topic: {default_topic}
Affiliate focus: {affiliate_focus}

{affiliate_context}

Generate the run() body that:
1. Builds a system prompt for a revenue-focused content writer
2. Builds a detailed user prompt asking GPT to generate affiliate-rich content about `topic`
3. Calls result = self.ai(prompt, system=system, max_tokens=2000)
4. Builds a markdown `output` string combining a header and the result
5. Naturally embeds 2-3 affiliate links in the output where contextually appropriate

The content should be SEO-optimized, valuable to readers, and drive clicks to affiliate links.
Focus niche: {default_topic}

Return ONLY the 8-space-indented Python code for the run() method body.
End with:  output = header + \"\\n\\n\" + result + \"\\n\\n\" + footer
(or similar final string assignment)"""

        from core.llm_client import safe_openai_call
        resp = safe_openai_call(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=1500,
            temperature=0.5,
            bot_name="superagent.run_body",
        )

        run_body = resp.choices[0].message.content.strip()

        # Strip any accidental markdown fences
        run_body = re.sub(r"^```python\s*", "", run_body)
        run_body = re.sub(r"\s*```$", "", run_body)

        # Ensure proper indentation (8 spaces inside run())
        lines = run_body.splitlines()
        indented_lines = []
        for line in lines:
            if line.strip() == "":
                indented_lines.append("")
            elif line.startswith("        "):
                indented_lines.append(line)
            elif line.startswith("    "):
                indented_lines.append("    " + line)
            else:
                indented_lines.append("        " + line)
        run_body = "\n".join(indented_lines)

        # Class name: 72_crypto_reviewer → CryptoReviewerBot
        parts = re.sub(r"^\d+_", "", name).split("_")
        class_name = "".join(p.capitalize() for p in parts) + "Bot"

        code = _BOT_TEMPLATE.format(
            bot_path=f"bots/{category}/{name}/bot.py",
            description=description,
            goal=goal,
            class_name=class_name,
            bot_name=name,
            category=category,
            default_topic=default_topic,
            run_body=run_body,
        )

        return code

    # ─── Interactive Chat ─────────────────────────────────────────────────────

    def chat(self, message: str) -> Dict:
        """
        Natural-language interface — user can instruct the SuperAgent directly.
        Understands intent, responds in persona, and executes actions as needed.
        """
        # Gather lightweight context
        try:
            assessment = self.assess()
            ctx_revenue = assessment.get("revenue_today", 0)
            ctx_goal = assessment.get("daily_goal", 10)
            all_bots = assessment.get("all_bot_names", [])
        except Exception:
            ctx_revenue = self.revenue_today
            ctx_goal = self.daily_revenue_goal
            all_bots = sorted(self.orch.bots.keys())

        recent_log = "\n".join(
            f"  [{e['ts']}] {e['action']}: {e['reason'][:70]}"
            for e in self.decision_log[-6:]
        )

        system = (
            "You are the WheellsVerse SuperAgent — an autonomous AI revenue assistant "
            "for Jhon Wheeler (J.K. Blaze). You manage 70+ bots that generate affiliate income. "
            "You can run bots, create new ones, upgrade existing ones, start/stop auto-mode, "
            "set revenue goals, explain what's happening, and give strategy advice. "
            "When the user asks you to DO something, include it in 'actions'. "
            "Respond in first-person, confidently. Be concise and direct. "
            "Return ONLY valid JSON — no markdown outside the JSON."
        )

        prompt = f"""User message: "{message}"

Current state:
- Revenue today: ${ctx_revenue:.2f} / goal ${ctx_goal:.2f}
- Status: {self.status} | Cycles: {self.cycle_count} | Bots created by me: {len(self.created_bots)}
- Total bots loaded: {len(self.orch.bots)}

Available bots (use exact names in actions):
{chr(10).join(f'  {b}' for b in all_bots[:40])}
{'  ... (+more)' if len(all_bots) > 40 else ''}

My recent decisions:
{recent_log or '  (none yet)'}

Respond with JSON:
{{
  "reply": "Your direct, helpful response to the user",
  "actions": [
    // Include ONLY if the user is asking you to DO something
    // run_parallel: {{"type":"run_parallel","targets":["bot1","bot2"],"reason":"..."}}
    // run_bot:      {{"type":"run_bot","target":"category/name","kwargs":{{}},"reason":"..."}}
    // create_bot:   {{"type":"create_bot","name":"N_slug","category":"specialized","description":"...","goal":"...","default_topic":"...","affiliate_focus":"all"}}
    // upgrade_bot:  {{"type":"upgrade_bot","target":"category/name","improvement":"..."}}
    // Leave empty [] if this is a question/status request
  ]
}}"""

        try:
            from core.llm_client import safe_openai_call
            resp = safe_openai_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                max_tokens=900,
                temperature=0.7,
                response_format={"type": "json_object"},
                bot_name="superagent.chat",
            )
            data = json.loads(resp.choices[0].message.content)
            reply = data.get("reply", "Done.")
            actions = data.get("actions", [])

            results = []
            if actions:
                results = self.execute({
                    "actions": actions,
                    "analysis": f"Chat task: {message[:80]}",
                    "priority": "chat",
                    "daily_message": "",
                })

            self._log("CHAT", f"User: {message[:70]}", f"Reply: {reply[:70]}")
            return {
                "reply": reply,
                "actions_taken": len(results),
                "results": results,
            }
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return {
                "reply": f"I ran into an error: {e}",
                "actions_taken": 0,
                "results": [],
            }

    # ─── Full Cycle ───────────────────────────────────────────────────────────

    def run_cycle(self) -> Dict:
        """
        Full autonomous cycle: assess → plan → execute.
        Returns summary dict for the API.
        """
        if self.status == "running":
            return {"status": "busy", "message": "Cycle already running"}

        self.status = "running"
        start = time.time()
        self.cycle_count += 1

        self._log(
            "CYCLE_START",
            f"Cycle #{self.cycle_count} beginning",
            f"Daily goal: ${self.daily_revenue_goal:.2f}",
        )

        try:
            assessment = self.assess()
            plan = self.plan(assessment)
            results = self.execute(plan)

            duration = round(time.time() - start, 1)
            summary = {
                "cycle": self.cycle_count,
                "duration_s": duration,
                "revenue_today": assessment["revenue_today"],
                "daily_goal": assessment["daily_goal"],
                "goal_met": assessment["goal_met"],
                "actions_taken": len(results),
                "analysis": plan.get("analysis", ""),
                "daily_message": plan.get("daily_message", ""),
                "results": results,
            }

            self._log(
                "CYCLE_DONE",
                f"Cycle #{self.cycle_count} complete in {duration}s",
                f"Revenue today: ${assessment['revenue_today']:.2f} | "
                f"Actions: {len(results)}",
            )
            self._save_meta()
            return summary

        except Exception as e:
            logger.error(f"Cycle failed: {e}")
            self._log("ERROR", f"Cycle #{self.cycle_count} failed: {e}", level="ERROR")
            return {"status": "error", "error": str(e)}
        finally:
            self.status = "idle"

    # ─── Autonomous Mode ──────────────────────────────────────────────────────

    def start_auto(self, interval_minutes: int = 120):
        """Start the autonomous cycle loop in a background thread."""
        if self._auto_thread and self._auto_thread.is_alive():
            return {"status": "already_running", "interval_minutes": interval_minutes}

        self._stop_event.clear()

        def _loop():
            logger.info(f"SuperAgent auto-mode started (every {interval_minutes}m)")
            while not self._stop_event.is_set():
                self.run_cycle()
                # Wait for interval, checking stop every 30s
                for _ in range(interval_minutes * 2):
                    if self._stop_event.is_set():
                        break
                    time.sleep(30)
            logger.info("SuperAgent auto-mode stopped")

        self._auto_thread = threading.Thread(target=_loop, daemon=True, name="SuperAgent-Auto")
        self._auto_thread.start()
        self._log("AUTO_START", "Autonomous mode started", f"Interval: {interval_minutes}m")
        return {"status": "started", "interval_minutes": interval_minutes}

    def stop_auto(self):
        """Stop the autonomous cycle loop."""
        self._stop_event.set()
        self._log("AUTO_STOP", "Autonomous mode stopped by user")
        return {"status": "stopped"}

    # ─── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        auto_running = bool(self._auto_thread and self._auto_thread.is_alive()
                            and not self._stop_event.is_set())
        return {
            "status": self.status,
            "auto_mode": auto_running,
            "cycle_count": self.cycle_count,
            "created_bots_count": len(self.created_bots),
            "created_bots": self.created_bots[-10:],  # last 10
            "revenue_today": round(self.revenue_today, 2),
            "daily_goal": self.daily_revenue_goal,
            "log": self.decision_log[-50:],  # last 50 entries
            "version": self.VERSION,
        }

    def set_goal(self, daily_usd: float):
        """Manually set the daily revenue goal."""
        self.daily_revenue_goal = max(1.0, float(daily_usd))
        self._save_meta()
        self._log("GOAL_SET", f"Daily revenue goal updated to ${self.daily_revenue_goal:.2f}")
        return {"daily_goal": self.daily_revenue_goal}


# ─── Orchestrator hot-load patch ──────────────────────────────────────────────
# Adds _load_single_bot() to orchestrator if it doesn't have it yet

def _patch_orchestrator(orch):
    """Inject _load_single_bot() into an existing Orchestrator instance."""
    if hasattr(orch, "_load_single_bot"):
        return

    import importlib.util as _ilu

    def _load_single_bot(self, bot_py: Path, bot_name: str, category: str, config: dict):
        full_name = f"{category}/{bot_name}"
        try:
            spec = _ilu.spec_from_file_location(bot_name, bot_py)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # Find the Bot class
            bot_class = None
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (isinstance(obj, type)
                        and attr.endswith("Bot")
                        and attr != "BaseBot"):
                    bot_class = obj
                    break
            if bot_class is None:
                raise ValueError(f"No *Bot class found in {bot_py}")
            instance = bot_class()
            self.bots[full_name] = instance
            self.registry[full_name] = {
                "name": bot_name,
                "category": category,
                "path": str(bot_py),
                "config": config,
                "description": config.get("description", "SuperAgent bot"),
                "schedule": config.get("schedule", None),
            }
            logger.info(f"Hot-registered: {full_name}")
        except Exception as e:
            logger.error(f"Hot-register failed for {full_name}: {e}")
            raise

    import types
    orch._load_single_bot = types.MethodType(_load_single_bot, orch)


# ─── Singleton ────────────────────────────────────────────────────────────────

_superagent: Optional[SuperAgent] = None


def get_superagent(orchestrator=None) -> SuperAgent:
    global _superagent
    if _superagent is None:
        from core.orchestrator import get_orchestrator
        orch = orchestrator or get_orchestrator()
        _patch_orchestrator(orch)
        _superagent = SuperAgent(orchestrator=orch)
    return _superagent
