#!/usr/bin/env python3
"""
bots/campaigns/viral_post_campaign/publish_campaign.py
─────────────────────────────────────────────────────────────────────────────
One-shot publisher for an already-generated viral campaign markdown file.

Parses the markdown, splits by platform section, extracts each post's
FULL POST COPY + HASHTAGS, and publishes each one to its native platform:
  • FACEBOOK posts → Facebook Page
  • INSTAGRAM posts → Instagram (DALL-E image auto-generated)
  • TWITTER posts → Twitter/X

Usage:
  python publish_campaign.py                          # auto-finds latest file
  python publish_campaign.py --file path/to/file.md  # specific file
  python publish_campaign.py --dry-run               # print posts, don't post
─────────────────────────────────────────────────────────────────────────────
"""
import re
import sys
import time
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

CAMPAIGN_OUTPUT_DIR = ROOT / "outputs" / "campaigns" / "Viral Post Campaign"


def find_latest_campaign_file() -> Path:
    """Find the most recently generated campaign markdown file."""
    files = sorted(CAMPAIGN_OUTPUT_DIR.glob("viral_campaign_*.md"), key=lambda f: f.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No campaign files found in {CAMPAIGN_OUTPUT_DIR}")
    return files[-1]


def parse_campaign_file(md_path: Path) -> list:
    """
    Parse a viral campaign markdown file into individual posts.

    Returns:
        List of dicts: {platform, post_num, title, copy, hashtags}
    """
    md = md_path.read_text(encoding="utf-8")
    posts = []

    # Split by platform section headers
    platform_pattern = re.compile(
        r"^## (FACEBOOK|INSTAGRAM|TWITTER) POSTS\s*$", re.MULTILINE | re.IGNORECASE
    )
    parts = platform_pattern.split(md)
    # parts: [preamble, "FACEBOOK", fb_block, "INSTAGRAM", ig_block, "TWITTER", tw_block]

    i = 1
    while i < len(parts) - 1:
        platform = parts[i].strip().lower()
        block = parts[i + 1]
        i += 2

        # Split into individual posts (### POST N — ...)
        post_sections = re.split(r"^(### POST \d+.*?)$", block, flags=re.MULTILINE)
        # post_sections: [before_first, "### POST 1 — ...", content1, "### POST 2 — ...", content2, ...]

        j = 1
        while j < len(post_sections) - 1:
            header = post_sections[j].strip()
            content = post_sections[j + 1]
            j += 2

            post_num_match = re.search(r"POST (\d+)", header)
            post_num = int(post_num_match.group(1)) if post_num_match else 0

            # Extract HOOK (used as title)
            hook_match = re.search(r"\*\*🪝 HOOK\*\*\s*\n(.+)", content)
            hook = hook_match.group(1).strip() if hook_match else header

            # Extract FULL POST COPY
            copy_match = re.search(
                r"\*\*📣 FULL POST COPY\*\*\s*\n(.*?)(?=\n\*\*[#️⃣🖼🧠]|\Z)",
                content, re.DOTALL
            )
            copy = copy_match.group(1).strip() if copy_match else content.strip()[:600]

            # Fallback: if copy is empty, use the value offer + social proof + hook
            if not copy:
                copy = hook

            # Extract HASHTAGS
            tag_match = re.search(
                r"\*\*#️⃣ HASHTAGS\*\*\s*\n(.*?)(?=\n\*\*[🖼🧠]|\Z)",
                content, re.DOTALL
            )
            raw_tags = tag_match.group(1).strip() if tag_match else ""
            hashtags = re.findall(r"#(\w+)", raw_tags)

            posts.append({
                "platform": platform,
                "post_num": post_num,
                "title": hook[:100],
                "copy": copy,
                "hashtags": hashtags or ["AI", "MakeMoneyOnline", "Automation"],
            })

    return posts


def _post_twitter_direct(copy: str, hashtags: list) -> dict:
    """Post to Twitter using the direct client (bypasses broken browser thread method)."""
    from core.twitter import get_twitter
    tw = get_twitter()
    tags = " ".join(f"#{h}" for h in (hashtags or [])[:3])
    text = copy.strip()
    # Trim to fit 280 chars including hashtags
    max_body = 275 - len(tags) - 1
    if len(text) > max_body:
        text = text[:max_body - 1].rsplit(" ", 1)[0] + "…"
    full_text = f"{text} {tags}".strip() if tags else text
    result = tw.post_tweet(full_text)
    if result:
        return {"platform": "twitter", "status": "posted", "url": result.get("url", "")}
    return {"platform": "twitter", "status": "error", "error": "No result from post_tweet"}


def publish_all(posts: list, dry_run: bool = False) -> list:
    """Publish each post to its native platform."""
    if not dry_run:
        from core.publish_pipeline import get_publisher
        pub = get_publisher()

    results = []
    total = len(posts)

    print(f"\n{'=' * 60}")
    print(f"  PUBLISHING {total} POSTS")
    print(f"{'=' * 60}")

    fb_posts = [p for p in posts if p["platform"] == "facebook"]
    ig_posts = [p for p in posts if p["platform"] == "instagram"]
    tw_posts = [p for p in posts if p["platform"] == "twitter"]

    for group_label, group in [
        ("FACEBOOK", fb_posts),
        ("INSTAGRAM", ig_posts),
        ("TWITTER", tw_posts),
    ]:
        if not group:
            continue
        print(f"\n── {group_label} ({len(group)} posts) ──────────────────────")
        for post in group:
            label = f"  Post {post['post_num']}: {post['title'][:55]}..."
            print(label)

            if dry_run:
                print(f"  [DRY RUN] Would publish to {post['platform'].upper()}")
                print(f"  Copy preview: {post['copy'][:120]}...")
                print(f"  Hashtags: {post['hashtags'][:5]}")
                results.append({**post, "status": "dry_run"})
                continue

            try:
                if post["platform"] == "twitter":
                    if dry_run:
                        results.append({**post, "status": "dry_run"})
                        print("  [DRY RUN] Would post to TWITTER")
                        continue
                    platform_result = _post_twitter_direct(post["copy"], post["hashtags"])
                else:
                    result = pub.publish(
                        content=post["copy"],
                        title=post["title"],
                        platforms=[post["platform"]],
                        hashtags=post["hashtags"],
                    )
                    platform_result = result.get("results", [{}])[0] if result.get("results") else {}

                status = platform_result.get("status", "unknown")
                post_id = platform_result.get("post_id") or platform_result.get("url", "")
                results.append({**post, "status": status, "post_id": post_id})
                icon = "✅" if status not in ("error", "skipped") else "⚠️"
                print(f"  {icon} {status}" + (f" — {post_id}" if post_id else ""))
            except Exception as e:
                results.append({**post, "status": "error", "error": str(e)})
                print(f"  ❌ Error: {e}")

            # Natural delay — longer for Twitter to avoid rate limits
            time.sleep(10 if post["platform"] == "twitter" else 4)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    if not dry_run:
        published = sum(1 for r in results if r["status"] not in ("error", "skipped", "dry_run"))
        skipped = sum(1 for r in results if r["status"] == "skipped")
        errors = sum(1 for r in results if r["status"] == "error")
        print(f"  ✅ Published: {published}  ⚠️ Skipped: {skipped}  ❌ Errors: {errors}")
    else:
        print(f"  ✅ Dry run complete — {len(results)} posts ready to publish")
    print(f"{'=' * 60}\n")

    return results


def main():
    parser = argparse.ArgumentParser(description="Publish generated viral campaign posts")
    parser.add_argument("--file", type=str, default=None, help="Path to campaign markdown file")
    parser.add_argument("--dry-run", action="store_true", help="Print posts without publishing")
    args = parser.parse_args()

    # ── Find file ─────────────────────────────────────────────────────────────
    if args.file:
        md_path = Path(args.file)
        if not md_path.is_absolute():
            md_path = ROOT / md_path
    else:
        md_path = find_latest_campaign_file()

    print(f"\n📂 Campaign file: {md_path.name}")

    # ── Parse ─────────────────────────────────────────────────────────────────
    posts = parse_campaign_file(md_path)
    print(f"📋 Posts parsed: {len(posts)} total "
          f"({sum(1 for p in posts if p['platform'] == 'facebook')} FB, "
          f"{sum(1 for p in posts if p['platform'] == 'instagram')} IG, "
          f"{sum(1 for p in posts if p['platform'] == 'twitter')} TW)")

    if not posts:
        print("❌ No posts found in file. Check markdown format.")
        sys.exit(1)

    # ── Publish ───────────────────────────────────────────────────────────────
    results = publish_all(posts, dry_run=args.dry_run)

    # ── Telegram notification ─────────────────────────────────────────────────
    if not args.dry_run:
        try:
            from core.telegram import notify
            ok = sum(1 for r in results if r["status"] not in ("error", "skipped"))
            notify(f"📣 Viral Campaign Published\n✅ {ok}/{len(results)} posts live\n📁 {md_path.name}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
