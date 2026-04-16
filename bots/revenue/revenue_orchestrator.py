#!/usr/bin/env python3
"""
WheellsVerse Revenue Orchestrator
Manages all 10 revenue streams. Runs daily actions, tracks revenue, reports to Telegram.
Can run all streams or individual streams on demand.

Revenue Streams:
  01: Prompt Bible        — $47 Gumroad product. Daily promo posts.
  02: Mini-Course         — $97 course. Daily promo posts.
  03: Coinbase Daily      — Affiliate posts (up to $10/signup). 1 post/day.
  04: Bot Pack            — $197/6mo. Daily promo + buyer onboarding.
  05: Crypto Newsletter   — $9/month recurring. Weekly send.
  06: YouTube Channel     — Script factory + metadata. 1 video/day.
  07: SEO Blog            — 1 article/day. Affiliate monetized.
  08: Digital Store       — $299 bundle. Daily promo.
  09: NEXORA Beta         — $29-$49/month. Daily creator recruitment.
  10: WhatsApp Circle     — $19/month. Daily tips to members.

Target Combined MRR:
  Conservative: $3,000-$5,000/month
  Realistic:    $7,000-$10,000/month
  Optimistic:   $15,000-$20,000/month
"""
import sys
import importlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

STREAMS = {
    "01_prompt_bible": {
        "module": "bots.revenue.01_prompt_bible.bot",
        "class": "PromptBibleBot",
        "action": "promote",
        "schedule": "daily",
        "revenue_model": "one-time $47",
        "target_monthly": 2000,
    },
    "02_mini_course": {
        "module": "bots.revenue.02_mini_course.bot",
        "class": "MiniCourseBot",
        "action": "promote",
        "schedule": "daily",
        "revenue_model": "one-time $97",
        "target_monthly": 1940,
    },
    "03_coinbase_daily": {
        "module": "bots.revenue.03_coinbase_daily.bot",
        "class": "CoinbaseDailyBot",
        "action": "post",
        "schedule": "daily",
        "revenue_model": "affiliate $10/signup",
        "target_monthly": 1000,
    },
    "04_bot_pack": {
        "module": "bots.revenue.04_bot_pack.bot",
        "class": "BotPackBot",
        "action": "promote",
        "schedule": "daily",
        "revenue_model": "one-time $197",
        "target_monthly": 1970,
    },
    "05_crypto_newsletter": {
        "module": "bots.revenue.05_crypto_newsletter.bot",
        "class": "CryptoNewsletterBot",
        "action": "promote",
        "schedule": "daily",
        "revenue_model": "recurring $9/month",
        "target_monthly": 1800,
    },
    "06_youtube_channel": {
        "module": "bots.revenue.06_youtube_channel.bot",
        "class": "YouTubeChannelBot",
        "action": "script",
        "schedule": "daily",
        "revenue_model": "ad revenue + affiliate",
        "target_monthly": 500,
    },
    "07_seo_blog": {
        "module": "bots.revenue.07_seo_blog.bot",
        "class": "SEOBlogBot",
        "action": "write",
        "schedule": "daily",
        "revenue_model": "affiliate SEO traffic",
        "target_monthly": 1500,
    },
    "08_digital_store": {
        "module": "bots.revenue.08_digital_store.bot",
        "class": "DigitalStoreBot",
        "action": "promote",
        "schedule": "daily",
        "revenue_model": "bundle $299",
        "target_monthly": 1495,
    },
    "09_nexora_beta": {
        "module": "bots.revenue.09_nexora_beta.bot",
        "class": "NexoraBetaBot",
        "action": "recruit",
        "schedule": "daily",
        "revenue_model": "recurring $29-$49/month",
        "target_monthly": 2450,
    },
    "10_whatsapp_circle": {
        "module": "bots.revenue.10_whatsapp_circle.bot",
        "class": "WhatsAppCircleBot",
        "action": "daily_tip",
        "schedule": "daily",
        "revenue_model": "recurring $19/month",
        "target_monthly": 3800,
    },
}

TOTAL_TARGET = sum(s["target_monthly"] for s in STREAMS.values())


def run_stream(stream_id: str, action: str = None, **kwargs) -> dict:
    """Run a single revenue stream."""
    cfg = STREAMS.get(stream_id)
    if not cfg:
        return {"error": f"Unknown stream: {stream_id}"}
    try:
        mod = importlib.import_module(cfg["module"].replace(".", "/").replace("/", "."))
        cls = getattr(mod, cfg["class"])
        bot = cls()
        result = bot.execute(action=action or cfg["action"], **kwargs)
        return {"stream": stream_id, "status": "ok", "result": result}
    except Exception as e:
        return {"stream": stream_id, "status": "error", "error": str(e)}


def run_all_streams(streams: list = None, **kwargs) -> list:
    """Run all revenue streams (or specified subset)."""
    targets = streams or list(STREAMS.keys())
    results = []
    for stream_id in targets:
        print(f"  → Running {stream_id}...", flush=True)
        result = run_stream(stream_id, **kwargs)
        results.append(result)
        status = "✅" if result.get("status") == "ok" else "❌"
        print(f"  {status} {stream_id}: {result.get('status')}", flush=True)
    return results


def daily_operations():
    """Run all daily revenue operations and report to Telegram."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    print(f"\n🚀 WheellsVerse Revenue Engine — {today}")
    print(f"Running {len(STREAMS)} revenue streams...\n")

    results = run_all_streams()

    ok = sum(1 for r in results if r.get("status") == "ok")
    fail = len(results) - ok

    # Send Telegram report
    try:
        from core.telegram import notify
        stream_status = "\n".join(
            f"{'✅' if r.get('status') == 'ok' else '❌'} {r['stream']}"
            for r in results
        )
        notify(
            f"💰 REVENUE ENGINE — {today}\n\n"
            f"{stream_status}\n\n"
            f"{'✅' if fail == 0 else '⚠️'} {ok}/{len(results)} streams OK\n"
            f"🎯 Monthly target: ${TOTAL_TARGET:,}/month\n"
            f"📊 Running 10 monetization streams 24/7"
        )
    except Exception as e:
        print(f"Telegram notify failed: {e}")

    return results


def revenue_dashboard() -> dict:
    """Generate revenue dashboard summary."""
    dashboard = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "streams": {},
        "total_monthly_target": TOTAL_TARGET,
    }
    for stream_id, cfg in STREAMS.items():
        dashboard["streams"][stream_id] = {
            "revenue_model": cfg["revenue_model"],
            "monthly_target": cfg["target_monthly"],
            "schedule": cfg["schedule"],
        }
    return dashboard


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="WheellsVerse Revenue Orchestrator")
    parser.add_argument("--run", nargs="*", help="Stream IDs to run (blank = all)")
    parser.add_argument("--stream", type=str, help="Run single stream")
    parser.add_argument("--action", type=str, help="Action override")
    parser.add_argument("--dashboard", action="store_true", help="Show revenue dashboard")
    parser.add_argument("--daily", action="store_true", help="Run daily operations")
    args = parser.parse_args()

    if args.dashboard:
        import json
        d = revenue_dashboard()
        print(json.dumps(d, indent=2))
        print(f"\n💰 Total Monthly Target: ${TOTAL_TARGET:,}")

    elif args.stream:
        result = run_stream(args.stream, action=args.action)
        print(f"\n{'✅' if result.get('status') == 'ok' else '❌'} {args.stream}: {result}")

    elif args.daily or args.run is not None:
        streams = args.run if args.run else None
        results = run_all_streams(streams)
        ok = sum(1 for r in results if r.get("status") == "ok")
        print(f"\n✅ {ok}/{len(results)} revenue streams executed")
        print(f"💰 Combined monthly target: ${TOTAL_TARGET:,}")

    else:
        # Default: run daily operations
        daily_operations()
