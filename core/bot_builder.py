#!/usr/bin/env python3
"""
core/bot_builder.py
─────────────────────────────────────────────────────────────────────────────
No-code visual bot builder.
Generates Python bots from templates using code_engine.
─────────────────────────────────────────────────────────────────────────────
"""

from typing import Dict, List

TEMPLATES: Dict[str, Dict] = {
    "social_poster": {
        "name": "Social Media Poster",
        "description": "Automatically generates and posts content to social media platforms",
        "icon": "📱",
        "config_fields": [
            {"name": "platforms", "label": "Platforms (comma separated)", "type": "text", "default": "twitter,instagram"},
            {"name": "niche", "label": "Content Niche", "type": "text", "default": "tech"},
            {"name": "posts_per_day", "label": "Posts per Day", "type": "number", "default": "3"},
            {"name": "tone", "label": "Tone", "type": "select", "options": ["professional", "casual", "humorous", "inspirational"], "default": "professional"},
        ],
    },
    "content_writer": {
        "name": "Content Writer",
        "description": "Generates blog posts, articles, and content based on topics",
        "icon": "✍️",
        "config_fields": [
            {"name": "topic_source", "label": "Topic Source (keyword/rss/trending)", "type": "text", "default": "trending"},
            {"name": "output_format", "label": "Output Format", "type": "select", "options": ["markdown", "html", "plain"], "default": "markdown"},
            {"name": "word_count", "label": "Target Word Count", "type": "number", "default": "1200"},
            {"name": "niche", "label": "Niche/Topic Area", "type": "text", "default": "AI and automation"},
        ],
    },
    "data_scraper": {
        "name": "Data Scraper",
        "description": "Scrapes and processes data from websites",
        "icon": "🕷️",
        "config_fields": [
            {"name": "target_url", "label": "Target URL Pattern", "type": "text", "default": "https://example.com"},
            {"name": "data_fields", "label": "Fields to Extract (comma separated)", "type": "text", "default": "title,price,description"},
            {"name": "output_format", "label": "Output Format", "type": "select", "options": ["json", "csv", "database"], "default": "json"},
            {"name": "schedule", "label": "Run Every (minutes)", "type": "number", "default": "60"},
        ],
    },
    "email_sender": {
        "name": "Email Campaign Bot",
        "description": "Sends automated email campaigns using templates",
        "icon": "📧",
        "config_fields": [
            {"name": "campaign_type", "label": "Campaign Type", "type": "select", "options": ["newsletter", "drip", "announcement", "follow_up"], "default": "newsletter"},
            {"name": "subject_line", "label": "Subject Line Template", "type": "text", "default": "{{topic}} — Weekly Update"},
            {"name": "from_name", "label": "From Name", "type": "text", "default": "WheellsVerse"},
            {"name": "frequency", "label": "Send Frequency", "type": "select", "options": ["daily", "weekly", "monthly"], "default": "weekly"},
        ],
    },
    "scheduler_bot": {
        "name": "Task Scheduler Bot",
        "description": "Runs scheduled tasks and automations at set intervals",
        "icon": "⏰",
        "config_fields": [
            {"name": "task_type", "label": "Task Type", "type": "select", "options": ["data_collection", "report_generation", "cleanup", "api_call"], "default": "data_collection"},
            {"name": "interval_minutes", "label": "Run Every (minutes)", "type": "number", "default": "60"},
            {"name": "notification", "label": "Send Notification on Complete", "type": "select", "options": ["yes", "no"], "default": "yes"},
            {"name": "retry_on_fail", "label": "Retry on Failure", "type": "select", "options": ["yes", "no"], "default": "yes"},
        ],
    },
    "market_monitor": {
        "name": "Market Monitor Bot",
        "description": "Monitors stock prices and crypto, sends alerts on movements",
        "icon": "📈",
        "config_fields": [
            {"name": "symbols", "label": "Symbols to Monitor (comma separated)", "type": "text", "default": "BTC,ETH,AAPL"},
            {"name": "alert_threshold", "label": "Alert Threshold %", "type": "number", "default": "5"},
            {"name": "check_interval", "label": "Check Every (minutes)", "type": "number", "default": "15"},
            {"name": "alert_channel", "label": "Alert Channel (telegram/discord/email)", "type": "text", "default": "telegram"},
        ],
    },
}


def get_templates() -> List[Dict]:
    """Return all templates with their config fields."""
    return [
        {"id": k, **{kk: vv for kk, vv in v.items() if kk != "config_fields"},
         "config_fields": v["config_fields"]}
        for k, v in TEMPLATES.items()
    ]


def _build_prompt(template_id: str, config: Dict, bot_name: str) -> str:
    """Build a code generation prompt from a template + config."""
    template = TEMPLATES.get(template_id)
    if not template:
        raise ValueError(f"Unknown template: {template_id}")

    config_str = "\n".join(f"  - {f['label']}: {config.get(f['name'], f.get('default', ''))}"
                           for f in template["config_fields"])

    return (
        f"Create a Python bot named '{bot_name}' that is a {template['name']}.\n\n"
        f"Description: {template['description']}\n\n"
        f"Configuration:\n{config_str}\n\n"
        f"Requirements:\n"
        f"1. Extend the BaseBot class from core.base_bot\n"
        f"2. Implement run() method with the main bot logic\n"
        f"3. Add proper logging with self.log()\n"
        f"4. Add error handling with try/except\n"
        f"5. Use os.getenv() for API keys\n"
        f"6. Make it production-ready with no placeholder code\n"
        f"7. Add a main() function and if __name__=='__main__' block\n\n"
        f"Return ONLY complete, runnable Python code."
    )


def build_from_template(template_id: str, config: Dict, bot_name: str) -> Dict:
    """
    Build a bot from a template.
    Returns {code, valid, error, path}
    """
    from core.code_engine import generate_code, validate_code, save_code
    prompt = _build_prompt(template_id, config, bot_name)
    code = generate_code(prompt)
    valid, err = validate_code(code)
    if not valid:
        return {"code": code, "valid": False, "error": err, "path": None}
    path = save_code(bot_name, code)
    return {"code": code, "valid": True, "error": None, "path": str(path)}


def preview_from_template(template_id: str, config: Dict, bot_name: str = "preview_bot") -> str:
    """Generate code preview without saving."""
    from core.code_engine import generate_code
    prompt = _build_prompt(template_id, config, bot_name)
    return generate_code(prompt)
