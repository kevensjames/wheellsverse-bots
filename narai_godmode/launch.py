"""
NarAI book-launch fan-out — called after a KDP launch to cross-post on social.

Usage from Python:
    from narai_godmode.launch import post_to_all
    result = post_to_all(title="My Book", genre="mystery",
                        ebook_url="...", paperback_url="...")
    # {"x": {ok, url}, "fb": {ok, id}, "ig": {ok, id}, "gmail": {ok, id}}

Or from the CLI:
    python -m narai_godmode.launch --title "My Book" --genre mystery \\
        --ebook-url "..." --paperback-url "..." [--dry-run]

Dry-run prints all drafts to stdout without posting — use to review copy first.
"""
from __future__ import annotations

from typing import Any

# ── Genre-keyed tagline generator ────────────────────────────────────────────

GENRE_HOOKS: dict[str, tuple[str, list[str]]] = {
    # (generic hook template, hashtags)
    "adventure":  ("A pulse-pounding journey across continents awaits.",
                   ["adventurenovel", "amreading", "thriller", "actionpacked"]),
    "mystery":    ("Every suspect has a motive. Only one has the truth.",
                   ["mystery", "whodunit", "cozymystery", "detectivefiction"]),
    "romance":    ("Sometimes the right love story begins at the worst possible moment.",
                   ["romance", "romancebooks", "contemporaryromance", "loveyourself"]),
    "fantasy":    ("Magic costs more than the living can pay.",
                   ["fantasybooks", "epicfantasy", "darkfantasy", "magic"]),
    "sci_fi":     ("The future is closer — and stranger — than you think.",
                   ["scifi", "speculativefiction", "sffbooks", "hardscifi"]),
    "scifi":      ("The future is closer — and stranger — than you think.",
                   ["scifi", "speculativefiction", "sffbooks", "hardscifi"]),
    "historical": ("History remembers the powerful. Fiction remembers the rest.",
                   ["historicalfiction", "histfic", "historybooks", "bookstagram"]),
    "horror":     ("Some doors should stay closed. This one just opened.",
                   ["horrorbooks", "darkfiction", "thriller", "supernatural"]),
    "true_crime": ("The case files they didn't want you to read.",
                   ["truecrime", "truecrimebooks", "cybercrime", "crimeaddicts"]),
    "truecrime":  ("The case files they didn't want you to read.",
                   ["truecrime", "truecrimebooks", "cybercrime", "crimeaddicts"]),
    "self_help":  ("A no-BS roadmap from where you are to where you want to be.",
                   ["personalgrowth", "selfhelp", "mindset", "motivation"]),
    "selfhelp":   ("A no-BS roadmap from where you are to where you want to be.",
                   ["personalgrowth", "selfhelp", "mindset", "motivation"]),
    "childrens":  ("A bedtime story your kids will ask for again and again.",
                   ["childrensbooks", "kidlit", "bedtimestory", "picturebook"]),
}


def _genre_copy(genre: str) -> tuple[str, list[str]]:
    g = (genre or "").lower().strip()
    if g in GENRE_HOOKS:
        return GENRE_HOOKS[g]
    # Fallback for unknown genres
    return ("A new release from J.K. Blaze — out now.",
            ["amreading", "bookstagram", "newrelease", "indiebooks"])


# ── Per-platform copy drafters ───────────────────────────────────────────────

def draft_tweet(title: str, genre: str, ebook_url: str, paperback_url: str) -> str:
    hook, tags = _genre_copy(genre)
    tag_str = " ".join(f"#{t}" for t in tags[:3])
    url = ebook_url or paperback_url or ""
    # Hard 280-char ceiling
    body = f"📘 {title}\n\n{hook}\n\n{tag_str}"
    if url:
        body += f"\n\n{url}"
    return body[:280]


def draft_fb_post(title: str, genre: str, ebook_url: str, paperback_url: str) -> str:
    hook, tags = _genre_copy(genre)
    tag_str = " ".join(f"#{t}" for t in tags)
    genre_label = genre.replace("_", " ").title() if genre else "novel"
    return (
        f"🎉 New release: {title}\n\n"
        f"{hook}\n\n"
        f"A new {genre_label} by J.K. Blaze — available now as both a Kindle ebook "
        f"and a paperback on Amazon.\n\n"
        f"{tag_str}\n\n"
        f"#WheellsVerse #JKBlaze"
    )


def draft_ig_caption(title: str, genre: str, ebook_url: str, paperback_url: str) -> str:
    hook, tags = _genre_copy(genre)
    all_tags = tags + ["jkblaze", "wheellsverse", "newrelease", "bookclub", "indieauthor"]
    tag_str = " ".join(f"#{t}" for t in all_tags)
    genre_label = genre.replace("_", " ").title() if genre else "story"
    return (
        f"{title} 📖✨\n\n"
        f"{hook}\n\n"
        f"Now available in paperback and Kindle on Amazon.\n"
        f"(Link in bio — {genre_label} lovers, this one's for you.)\n\n"
        f"{tag_str}"
    )


def draft_email(title: str, genre: str, ebook_url: str, paperback_url: str) -> tuple[str, str]:
    hook, _ = _genre_copy(genre)
    genre_label = genre.replace("_", " ").title() if genre else "Book"
    subject = f"📘 {title} is live on Amazon"
    body = f"""
<h2>🚀 {title} has launched</h2>
<p><i>{hook}</i></p>
<ul>
  {"<li><b>Kindle:</b> <a href='" + ebook_url + "'>" + ebook_url + "</a></li>" if ebook_url else ""}
  {"<li><b>Paperback:</b> <a href='" + paperback_url + "'>" + paperback_url + "</a></li>" if paperback_url else ""}
</ul>
<p>Genre: {genre_label}</p>
<hr>
<p style="color:#888;font-size:12px;">Auto-sent by NarAI Godmode on launch.</p>
"""
    return subject, body


# ── Main fan-out ─────────────────────────────────────────────────────────────

def post_to_all(
    title: str,
    genre: str,
    ebook_url: str = "",
    paperback_url: str = "",
    platforms: tuple[str, ...] = ("x", "fb", "ig", "gmail"),
    as_fb_org: bool = True,
    ig_image_url: str = "",
    dry_run: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Post the book launch to every platform listed.

    platforms:     subset of ('x', 'fb', 'ig', 'gmail') — default is all four
    as_fb_org:     True posts as Page (default), False as user
    ig_image_url:  IG requires a public image URL — pass the cover's public link.
                   If empty, IG post is skipped with a note.
    dry_run:       print drafts without posting. Great for reviewing copy first.

    Returns a dict keyed by platform with {ok: bool, url/id: str, error?: str}.
    """
    tweet   = draft_tweet(title, genre, ebook_url, paperback_url)
    fb_body = draft_fb_post(title, genre, ebook_url, paperback_url)
    ig_cap  = draft_ig_caption(title, genre, ebook_url, paperback_url)
    email_subject, email_body = draft_email(title, genre, ebook_url, paperback_url)

    if dry_run:
        print(f"\n{'═' * 64}\nDRY RUN — {title}\n{'═' * 64}")
        print(f"\n🐦 X (tweet, {len(tweet)} chars):\n{tweet}")
        print(f"\n📘 Facebook:\n{fb_body}")
        print(f"\n📸 Instagram:\n{ig_cap}")
        print(f"\n📧 Gmail subject: {email_subject}")
        return {p: {"ok": False, "dry_run": True} for p in platforms}

    result: dict[str, dict[str, Any]] = {}

    # ── X ──
    if "x" in platforms:
        try:
            from .adapters import x_twitter
            r = x_twitter.post_tweet(tweet)
            result["x"] = {"ok": True, "url": r["url"], "id": r["id"]}
        except Exception as e:
            result["x"] = {"ok": False, "error": str(e)[:200]}

    # ── Facebook ──
    if "fb" in platforms:
        try:
            from .adapters import meta
            link = ebook_url or paperback_url
            r = meta.fb_post_text(fb_body, link=link or None)
            result["fb"] = {"ok": True, "id": r.get("id", ""), "url": r.get("url", "")}
        except Exception as e:
            result["fb"] = {"ok": False, "error": str(e)[:200]}

    # ── Instagram ──
    if "ig" in platforms:
        if not ig_image_url:
            result["ig"] = {"ok": False, "error": "skipped: needs ig_image_url (public HTTPS image)"}
        else:
            try:
                from .adapters import meta
                r = meta.ig_post_photo(image_url=ig_image_url, caption=ig_cap)
                result["ig"] = {"ok": True, "id": r.get("id", "")}
            except Exception as e:
                result["ig"] = {"ok": False, "error": str(e)[:200]}

    # ── Gmail (notify the author) ──
    if "gmail" in platforms:
        try:
            from .adapters import google as g
            me = g.whoami()
            sent = g.send_email(to=me["email"], subject=email_subject, body=email_body, html=True)
            result["gmail"] = {"ok": True, "id": sent.get("id", "")}
        except Exception as e:
            result["gmail"] = {"ok": False, "error": str(e)[:200]}

    return result


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    import json as _json

    p = argparse.ArgumentParser(description="Cross-post a book launch to X + FB + IG + Gmail.")
    p.add_argument("--title", required=True, help="Book title")
    p.add_argument("--genre", required=True, help="Genre (mystery, sci_fi, romance, ...)")
    p.add_argument("--ebook-url", default="", help="Kindle product URL")
    p.add_argument("--paperback-url", default="", help="Paperback product URL")
    p.add_argument("--ig-image", default="", help="Public HTTPS image URL for IG photo post")
    p.add_argument("--as-user", action="store_true", help="Post to FB as user, not page")
    p.add_argument("--skip", nargs="+", default=[], choices=["x", "fb", "ig", "gmail"],
                   help="Platforms to skip")
    p.add_argument("--dry-run", action="store_true", help="Print drafts only, don't post")
    args = p.parse_args()

    platforms = tuple(x for x in ("x", "fb", "ig", "gmail") if x not in args.skip)
    result = post_to_all(
        title=args.title, genre=args.genre,
        ebook_url=args.ebook_url, paperback_url=args.paperback_url,
        platforms=platforms, as_fb_org=not args.as_user,
        ig_image_url=args.ig_image, dry_run=args.dry_run,
    )
    print(_json.dumps(result, indent=2))
    return 0 if all(v.get("ok") or v.get("dry_run") for v in result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
