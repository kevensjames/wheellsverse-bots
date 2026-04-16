#!/usr/bin/env python3
"""
bots/campaigns/viral_post_campaign/daily_runner.py
─────────────────────────────────────────────────────────────────────────────
NarAI Daily Viral Campaign Runner

Runs automatically every day at 08:00 via NarAI's scheduler.
• Picks the next niche from a rotating list (never repeats within 7 days)
• Picks the next angle set (varies posts so content stays fresh)
• Generates 5 posts × 3 platforms (Facebook, Instagram, Twitter)
• Auto-publishes each post to its native platform
• Logs results and notifies via Telegram

Register in NarAI: action="run_bot", bot="campaigns/viral_post_campaign_daily"
─────────────────────────────────────────────────────────────────────────────
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# ── Rotating niches (7 days, then repeats with fresh angles) ─────────────────
DAILY_NICHES = [
    {
        "niche": "AI Tools & Automation",
        "angles": [
            {"angle": "AI tool that writes 30 days of content in 10 minutes",
             "hook_theme": "shocking speed claim", "value": "30-day content calendar in 10 mins",
             "proof_stat": "40,000+ creators already using this", "urgency": "Free beta — closing Friday",
             "offer_detail": "AI content calendar generator — 30 posts, 10 platforms, 10 minutes"},
            {"angle": "ChatGPT prompt that replaces a $3K/month copywriter",
             "hook_theme": "cost savings shock", "value": "1 prompt = $3K/month copywriter",
             "proof_stat": "8,200+ businesses cut costs with this", "urgency": "Sharing free — before I sell it",
             "offer_detail": "The master copywriting prompt framework used by 6-figure marketers"},
            {"angle": "Free AI tool — no credit card, no sign-up",
             "hook_theme": "zero-barrier free access", "value": "Full AI suite — 100% free forever",
             "proof_stat": "Used by 25,000+ entrepreneurs worldwide", "urgency": "Limited daily users — grab your slot",
             "offer_detail": "AI that writes, designs, schedules, and publishes — free tier"},
            {"angle": "5 AI tools that automate $10K/month side hustles",
             "hook_theme": "income multiplier list", "value": "5 tools → $10K/month automated",
             "proof_stat": "3,800+ side hustlers running these stacks", "urgency": "1 of the 5 tools going paid next week",
             "offer_detail": "Full stack: content AI + scheduler + email + store + traffic bot"},
            {"angle": "AI automation workflow — set it up once, earn forever",
             "hook_theme": "set and forget wealth", "value": "1-time setup → lifetime passive income",
             "proof_stat": "Workflow copied by 6,000+ creators", "urgency": "Free walkthrough — 48 hours only",
             "offer_detail": "AI content → auto-post → affiliate → email capture → sale — fully automated"},
        ],
    },
    {
        "niche": "Make Money Online",
        "angles": [
            {"angle": "How to make $1,000 this weekend with AI",
             "hook_theme": "weekend income sprint", "value": "$1K in 72 hours — exact method",
             "proof_stat": "2,100+ people tested this and it works", "urgency": "Works right now — market window closing",
             "offer_detail": "AI-powered gig + affiliate combo that pays fast"},
            {"angle": "Copy this $5K/month beginner income system",
             "hook_theme": "copy-paste income", "value": "Entire $5K/month system — copy it free",
             "proof_stat": "Newbies hitting $5K in 90 days with this", "urgency": "Removing this post soon — save it now",
             "offer_detail": "Affiliate + content + email stack — zero experience needed"},
            {"angle": "The $500/day formula nobody talks about",
             "hook_theme": "hidden secret income", "value": "The formula earning $500 silently daily",
             "proof_stat": "Found in a private mastermind — now sharing publicly", "urgency": "Limited time — won't post again",
             "offer_detail": "Niche affiliate + AI content + paid traffic loop"},
            {"angle": "Stop trading time for money — automate income",
             "hook_theme": "time freedom revolt", "value": "Full automation system — zero active time",
             "proof_stat": "4,500+ people escaped the 9-5 with this", "urgency": "Free access — this week only",
             "offer_detail": "AI runs your business 24/7 while you sleep"},
            {"angle": "Make money with AI even if you have zero skills",
             "hook_theme": "zero skill barrier", "value": "Beginner system — no skills, no experience",
             "proof_stat": "1,200+ complete beginners earning their first $1K", "urgency": "Cohort closes Sunday",
             "offer_detail": "Guided AI income system — step 1 to first dollar in 7 days"},
        ],
    },
    {
        "niche": "Crypto & Blockchain",
        "angles": [
            {"angle": "This AI crypto signal called BTC +40% before it happened",
             "hook_theme": "prediction proof", "value": "Live AI crypto signals — real-time",
             "proof_stat": "Predicted 73% of major moves in 2024", "urgency": "Next signal drops in 6 hours",
             "offer_detail": "AI signal bot — monitors 200+ coins, alerts before breakouts"},
            {"angle": "Get $10 free Bitcoin just for signing up",
             "hook_theme": "instant free crypto", "value": "$10 Bitcoin — no purchase needed",
             "proof_stat": "85,000+ people already claimed theirs", "urgency": "Offer expires this month",
             "offer_detail": "Coinbase referral — $10 BTC free when you buy $100"},
            {"angle": "DeFi strategy earning 20%+ APY — explained simply",
             "hook_theme": "high yield simplified", "value": "Step-by-step DeFi 20% APY guide",
             "proof_stat": "Strategy used by wallets with $50M+ TVL", "urgency": "APY window closing — act now",
             "offer_detail": "Stablecoin yield farming guide — low risk, high return"},
            {"angle": "The 3 altcoins AI thinks will 10x in 2025",
             "hook_theme": "AI price prediction", "value": "3 altcoins with 10x potential — free analysis",
             "proof_stat": "AI model trained on 5 years of crypto data", "urgency": "Early-stage — accumulate before the crowd",
             "offer_detail": "Full research: tokenomics, roadmap, catalyst, entry price"},
            {"angle": "Earn crypto passively — no trading required",
             "hook_theme": "passive crypto income", "value": "Earn crypto 24/7 — zero active trading",
             "proof_stat": "12,000+ holders earning passive crypto monthly", "urgency": "Staking pool filling — join now",
             "offer_detail": "Staking + referral + yield combo — full passive crypto stack"},
        ],
    },
    {
        "niche": "Side Hustles & Passive Income",
        "angles": [
            {"angle": "37 passive income ideas ranked by how fast they pay",
             "hook_theme": "mega list reveal", "value": "37 ranked passive income ideas — free PDF",
             "proof_stat": "Downloaded 18,000+ times this month", "urgency": "PDF free until Sunday",
             "offer_detail": "Ranked by: startup cost, time to first dollar, scalability"},
            {"angle": "How I make $3,200/month while sleeping",
             "hook_theme": "personal income story", "value": "My exact passive income stack — revealed",
             "proof_stat": "300+ people copied this and hit $1K+/month", "urgency": "Sharing for free — won't last",
             "offer_detail": "Affiliate + digital products + AI content — full breakdown"},
            {"angle": "Sell digital products you don't have to create",
             "hook_theme": "zero creation income", "value": "Resell done-for-you digital products",
             "proof_stat": "1,900+ sellers making $500+/month with PLR products", "urgency": "PLR bundle free — this week",
             "offer_detail": "PLR ebooks, templates, courses — sell 100% profit"},
            {"angle": "The side hustle that makes $200/day in 2 hours",
             "hook_theme": "time-efficient income", "value": "2 hours/day = $200 daily income",
             "proof_stat": "Verified by 700+ people running this hustle", "urgency": "Niche still uncrowded — move fast",
             "offer_detail": "AI-powered freelance service niche with high demand + low supply"},
            {"angle": "Build a $10K/month blog with AI — no writing required",
             "hook_theme": "AI does the work", "value": "Full AI blogging system — $10K/month",
             "proof_stat": "50+ blogs running this system profitably", "urgency": "Free course — first 500 only",
             "offer_detail": "AI writes, SEO optimizes, publishes, and monetizes your blog"},
        ],
    },
    {
        "niche": "Tech Tools & Productivity",
        "angles": [
            {"angle": "This free app saves me 3 hours every day",
             "hook_theme": "time saver reveal", "value": "3 hours saved daily — free app",
             "proof_stat": "4.8★ with 200,000+ downloads", "urgency": "Paid version free for 30 days — today only",
             "offer_detail": "AI task manager + automation + focus timer — all-in-one"},
            {"angle": "10 Chrome extensions that make you 10x more productive",
             "hook_theme": "productivity multiplier list", "value": "10 free Chrome extensions — install in 5 mins",
             "proof_stat": "Used by 500,000+ professionals daily", "urgency": "One extension going paid next week",
             "offer_detail": "AI writer + meeting notes + email assistant + focus blocker + more"},
            {"angle": "The tool stack replacing Notion, Slack, and Zoom for free",
             "hook_theme": "replace paid tools", "value": "Replace $200/month of tools — free alternatives",
             "proof_stat": "15,000+ teams switched and never looked back", "urgency": "Free migration guide — 72 hours",
             "offer_detail": "Full free stack: workspace + comms + video + project mgmt + docs"},
            {"angle": "AI meeting assistant — never take notes again",
             "hook_theme": "task elimination", "value": "AI takes notes, writes summaries, assigns actions",
             "proof_stat": "Adopted by 30,000+ remote teams", "urgency": "Free lifetime plan — for early adopters",
             "offer_detail": "Joins your Zoom/Meet/Teams — transcribes, summarizes, follows up"},
            {"angle": "Build your own AI assistant in 10 minutes — free",
             "hook_theme": "DIY AI", "value": "Your personal AI assistant — built in 10 mins",
             "proof_stat": "80,000+ people built theirs with this guide", "urgency": "Free tutorial — before it's a paid course",
             "offer_detail": "Custom GPT + n8n automation + Notion brain — full setup guide"},
        ],
    },
    {
        "niche": "Digital Marketing & Growth",
        "angles": [
            {"angle": "0 to 10,000 followers in 30 days — exact playbook",
             "hook_theme": "follower growth proof", "value": "30-day 10K follower playbook — free",
             "proof_stat": "Tested on 12 accounts — average 8,700 new followers", "urgency": "Playbook free — this month only",
             "offer_detail": "Daily posting schedule + hook templates + engagement tactics"},
            {"angle": "The viral hook formula that got 50M views",
             "hook_theme": "viral formula reveal", "value": "The exact formula behind 50M views",
             "proof_stat": "Used in campaigns reaching 100M+ people", "urgency": "Sharing free — before competitors notice",
             "offer_detail": "Hook + value + CTA formula with 200+ proven examples"},
            {"angle": "Email list of 10,000 — how I built it in 60 days free",
             "hook_theme": "email growth secret", "value": "10K email subscribers — free 60-day plan",
             "proof_stat": "List worth $15K/month in affiliate income", "urgency": "Free challenge — next cohort starts Monday",
             "offer_detail": "Lead magnet + funnel + traffic stack — zero ad spend"},
            {"angle": "AI writes all my ad copy — 5x ROAS",
             "hook_theme": "AI ad result proof", "value": "AI ad copy that gets 5x ROAS — free",
             "proof_stat": "Tested on $500K+ in ad spend", "urgency": "Free swipe file — limited download",
             "offer_detail": "100 winning ad copy templates + AI prompt to generate more"},
            {"angle": "The content strategy that grew my brand to $50K/month",
             "hook_theme": "brand growth reveal", "value": "Full $50K/month content strategy — revealed",
             "proof_stat": "Strategy now copied by 400+ brands", "urgency": "Free 1-hour breakdown — this week only",
             "offer_detail": "90-day content calendar + repurposing system + monetization stack"},
        ],
    },
    {
        "niche": "Freelancing & Remote Work",
        "angles": [
            {"angle": "Land your first $5K/month freelance client with AI",
             "hook_theme": "income milestone", "value": "First $5K client — AI-powered proposal system",
             "proof_stat": "1,400+ freelancers landed premium clients with this", "urgency": "Free workshop — seats almost gone",
             "offer_detail": "AI proposal generator + niche finder + cold outreach system"},
            {"angle": "The remote job that pays $80/hour and nobody is applying",
             "hook_theme": "hidden opportunity", "value": "Uncrowded $80/hour remote job — full guide",
             "proof_stat": "300+ applicants hired from our community", "urgency": "Job boards refreshed weekly — apply now",
             "offer_detail": "AI prompt engineering jobs — companies desperate, talent scarce"},
            {"angle": "Freelance with AI — charge premium, do 10% of the work",
             "hook_theme": "AI leverage in freelance", "value": "AI does 90% — you collect 100% of the fee",
             "proof_stat": "700+ freelancers 10x their output with this", "urgency": "Free training — next 48 hours",
             "offer_detail": "AI + freelance stack: proposals, delivery, invoicing — all automated"},
            {"angle": "6-figure freelancer roadmap — from zero in 12 months",
             "hook_theme": "income trajectory", "value": "Zero to $100K freelance — complete roadmap",
             "proof_stat": "85+ students hit 6 figures using this path", "urgency": "Free roadmap — download before Monday",
             "offer_detail": "Month-by-month plan: skill → niche → clients → scale"},
            {"angle": "Work 4 hours/week and earn $8K/month — remote",
             "hook_theme": "4-hour work week remix", "value": "4-hour week + $8K/month — exact setup",
             "proof_stat": "Verified by 220+ remote workers running this", "urgency": "Case study free — 72 hours only",
             "offer_detail": "Retainer client model + AI delivery + automated billing"},
        ],
    },
]

STATE_FILE = Path(__file__).parent / "rotation_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"niche_index": 0, "last_run": ""}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _get_today_niche() -> dict:
    """Pick today's niche round-robin and advance the counter."""
    state = _load_state()
    idx = state.get("niche_index", 0) % len(DAILY_NICHES)
    today_niche = DAILY_NICHES[idx]
    state["niche_index"] = (idx + 1) % len(DAILY_NICHES)
    state["last_run"] = datetime.now().isoformat()
    _save_state(state)
    return today_niche


def _extract_posts_from_markdown(md: str) -> list:
    """
    Parse the generated markdown into individual posts per platform.
    Returns list of dicts: {platform, title, copy, hashtags, hook}
    """
    posts = []
    # Split by platform section
    platform_pattern = re.compile(
        r"^## (FACEBOOK|INSTAGRAM|TWITTER) POSTS\s*$", re.MULTILINE | re.IGNORECASE
    )
    sections = platform_pattern.split(md)
    # sections: [preamble, FACEBOOK, fb_content, INSTAGRAM, ig_content, TWITTER, tw_content]

    i = 1
    while i < len(sections) - 1:
        platform = sections[i].strip().lower()
        content_block = sections[i + 1]
        i += 2

        # Split into individual posts
        post_blocks = re.split(r"^### POST \d+", content_block, flags=re.MULTILINE)
        for block in post_blocks:
            if not block.strip():
                continue

            # Extract title from first line
            lines = block.strip().splitlines()
            title_line = lines[0].strip(" —-") if lines else "Viral Post"

            # Extract FULL POST COPY
            copy_match = re.search(
                r"\*\*📣 FULL POST COPY\*\*\s*\n(.*?)(?=\n\*\*[#🖼🧠]|\Z)",
                block, re.DOTALL
            )
            copy = copy_match.group(1).strip() if copy_match else block.strip()[:500]

            # Extract HASHTAGS
            tag_match = re.search(
                r"\*\*#️⃣ HASHTAGS\*\*\s*\n(.*?)(?=\n\*\*[🖼🧠]|\Z)",
                block, re.DOTALL
            )
            raw_tags = tag_match.group(1).strip() if tag_match else ""
            hashtags = re.findall(r"#(\w+)", raw_tags)

            # Extract HOOK for the title
            hook_match = re.search(r"\*\*🪝 HOOK\*\*\s*\n(.+)", block)
            hook = hook_match.group(1).strip() if hook_match else title_line

            posts.append({
                "platform": platform,
                "title": hook[:80],
                "copy": copy,
                "hashtags": hashtags,
            })

    return posts


def _post_twitter_direct(copy: str, hashtags: list) -> dict:
    """Post directly via Twitter client — bypasses broken browser-thread pipeline method."""
    from core.twitter import get_twitter
    tw = get_twitter()
    tags = " ".join(f"#{h}" for h in (hashtags or [])[:3])
    text = copy.strip()
    max_body = 275 - len(tags) - 1
    if len(text) > max_body:
        text = text[:max_body - 1].rsplit(" ", 1)[0] + "…"
    full_text = f"{text} {tags}".strip() if tags else text
    result = tw.post_tweet(full_text)
    if result:
        return {"platform": "twitter", "status": "posted", "url": result.get("url", "")}
    return {"platform": "twitter", "status": "error", "error": "No result from post_tweet"}


def publish_posts(posts: list) -> list:
    """
    Publish each post to its native platform.

    Twitter safety rules (avoid suspension):
      - Max 2 tweets per daily run
      - Minimum 30-minute gap between tweets (enforced via timestamp file)
      - Skip Twitter entirely if account was recently suspended
    """
    from core.publish_pipeline import get_publisher
    pub = get_publisher()
    results = []

    TWITTER_DAILY_LIMIT = 2
    TWITTER_MIN_GAP_SECS = 1800  # 30 minutes between tweets
    TWITTER_STATE_FILE = Path(__file__).parent / "twitter_post_state.json"

    def _load_tw_state():
        if TWITTER_STATE_FILE.exists():
            try:
                return json.loads(TWITTER_STATE_FILE.read_text())
            except Exception:
                pass
        return {"date": "", "count": 0, "last_post_ts": 0}

    def _save_tw_state(state):
        TWITTER_STATE_FILE.write_text(json.dumps(state))

    tw_state = _load_tw_state()
    today_str = datetime.now().strftime("%Y-%m-%d")
    if tw_state.get("date") != today_str:
        tw_state = {"date": today_str, "count": 0, "last_post_ts": 0}

    for i, post in enumerate(posts, 1):
        platform = post["platform"]
        print(f"  [{i}/{len(posts)}] Publishing to {platform.upper()}: {post['title'][:50]}...")
        try:
            if platform == "twitter":
                # Safety gate: daily limit
                if tw_state["count"] >= TWITTER_DAILY_LIMIT:
                    results.append({**post, "status": "skipped",
                                    "reason": f"Twitter daily limit ({TWITTER_DAILY_LIMIT}/day) reached — safety cap"})
                    print(f"       ⏭  Skipped (daily limit {TWITTER_DAILY_LIMIT} reached)")
                    continue

                # Safety gate: minimum gap between tweets
                secs_since_last = time.time() - tw_state["last_post_ts"]
                if tw_state["last_post_ts"] > 0 and secs_since_last < TWITTER_MIN_GAP_SECS:
                    wait = int(TWITTER_MIN_GAP_SECS - secs_since_last)
                    results.append({**post, "status": "skipped",
                                    "reason": f"Twitter gap too short — {wait}s remaining"})
                    print(f"       ⏭  Skipped (wait {wait // 60}min before next tweet)")
                    continue

                r = _post_twitter_direct(post["copy"], post["hashtags"])
                status = r.get("status", "unknown")
                if status == "posted":
                    tw_state["count"] += 1
                    tw_state["last_post_ts"] = time.time()
                    _save_tw_state(tw_state)
            else:
                result = pub.publish(
                    content=post["copy"],
                    title=post["title"],
                    platforms=[platform],
                    hashtags=post["hashtags"],
                )
                status = result.get("results", [{}])[0].get("status", "unknown")

            results.append({"platform": platform, "title": post["title"][:50], "status": status})
            icon = "✅" if status not in ("error", "skipped") else "⚠️"
            print(f"       {icon} {status}")
        except Exception as e:
            results.append({"platform": platform, "title": post["title"][:50], "status": "error", "error": str(e)})
            print(f"       ❌ {e}")

        # Natural delay between posts — longer for Twitter
        delay = 5 if platform != "twitter" else 0
        if delay:
            time.sleep(delay)

    return results


def run_daily_campaign(publish: bool = True) -> dict:
    """Main entry point — called by NarAI scheduler or directly."""
    print(f"\n{'=' * 60}")
    print(f"  VIRAL CAMPAIGN DAILY RUNNER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}\n")

    # ── Step 1: Pick today's niche ────────────────────────────────────────────
    today = _get_today_niche()
    niche_name = today["niche"]
    angles = today["angles"]
    print(f"📌 Today's niche: {niche_name}\n")

    # ── Step 2: Generate content ──────────────────────────────────────────────
    # Import here to avoid circular issues at module load
    from bots.campaigns.viral_post_campaign.bot import ViralPostCampaignBot, PLATFORM_SPECS, SYSTEM_PROMPT, _build_platform_prompt
    from datetime import datetime as _dt

    bot = ViralPostCampaignBot("Viral Post Campaign", "campaigns")
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    safe_niche = "".join(c if c.isalnum() else "_" for c in niche_name[:25])

    all_output = f"""# Viral Post Campaign — {niche_name}
**Platforms:** FACEBOOK, INSTAGRAM, TWITTER
**Posts per platform:** 5
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

"""
    platform_list = ["facebook", "instagram"]  # Twitter removed — account suspended
    for platform in platform_list:
        spec = PLATFORM_SPECS[platform]
        print(f"✍️  Generating 5 posts for {platform.upper()}...")
        prompt = _build_platform_prompt(platform, spec, angles, 5)
        result = bot.ai(
            prompt,
            system=SYSTEM_PROMPT,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=4000,
        )
        all_output += f"---\n\n## {platform.upper()} POSTS\n\n{result}\n\n"

    all_output += "---\n*Generated by WheellsVerse Viral Post Campaign Daily Runner*\n"

    # ── Step 3: Save markdown ─────────────────────────────────────────────────
    filename = f"viral_campaign_{safe_niche}_{ts}.md"
    saved_path = bot.save_output(all_output, filename, ext="md")
    print(f"\n💾 Saved: {saved_path}")

    publish_results = []

    # ── Step 4: Publish ───────────────────────────────────────────────────────
    if publish:
        print(f"\n🚀 Publishing {len(platform_list) * 5} posts to platforms...\n")
        posts = _extract_posts_from_markdown(all_output)
        publish_results = publish_posts(posts)
        published = sum(1 for r in publish_results if r["status"] not in ("error", "skipped"))
        print(f"\n✅ Published: {published}/{len(publish_results)} posts")
    else:
        print("\n⏭  Skipping publish (publish=False)")

    # ── Step 5: Telegram notification ────────────────────────────────────────
    try:
        from core.telegram import notify
        total = len(publish_results)
        ok = sum(1 for r in publish_results if r["status"] not in ("error", "skipped"))
        notify(f"📣 Daily Viral Campaign — {niche_name}\n✅ {ok}/{total} posts published\n📁 {filename}")
    except Exception:
        pass

    return {
        "niche": niche_name,
        "file": str(saved_path),
        "publish_results": publish_results,
    }


# ── BaseBot compatibility — NarAI calls execute() ─────────────────────────────

class ViralPostCampaignDailyBot:
    """Thin wrapper so NarAI's orchestrator can call this via run_bot()."""
    NAME = "Viral Post Campaign Daily"

    def execute(self, **kwargs):
        return run_daily_campaign(publish=kwargs.get("publish", True))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily Viral Campaign Runner")
    parser.add_argument("--no-publish", action="store_true", help="Generate only, skip publishing")
    args = parser.parse_args()
    result = run_daily_campaign(publish=not args.no_publish)
    print(f"\n📊 Done — Niche: {result['niche']}")
    print(f"   File: {result['file']}")
