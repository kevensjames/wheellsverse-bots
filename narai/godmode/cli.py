"""
NarAI Godmode CLI + command router.

CLI usage:
  python -m narai.godmode.cli set amazon_kdp
  python -m narai.godmode.cli set printify
  python -m narai.godmode.cli list
  python -m narai.godmode.cli open amazon_kdp create_book
  python -m narai.godmode.cli open printify

Programmatic usage (for NarAI to call):
  from narai.godmode.cli import godmode
  godmode("open amazon_kdp create_book")
"""
import sys
import getpass

from .vault import Vault
from .adapters import amazon_kdp, generic
from .adapters import google as google_adapter
from .adapters import x_twitter, meta, canva as canva_adapter
from .adapters import linkedin as linkedin_adapter, tiktok as tiktok_adapter


# Services that use OAuth (not password). CLI routes them to their own flow.
OAUTH_SERVICES = {"google", "gmail", "drive", "calendar", "youtube", "sheets", "docs"}

API_ONLY_SERVICES = {
    "facebook": "Use Graph API with a user access token. Password login triggers bans.",
    "instagram": "Use Instagram Graph API. Password login triggers bans.",
    "x": "Use X API v2 with OAuth2. Password login triggers account locks.",
    "twitter": "Use X API v2 with OAuth2. Password login triggers account locks.",
    "linkedin": "Use LinkedIn API with OAuth2. Scraping logins get accounts banned.",
}


def cmd_set(args):
    if not args:
        print("Usage: set <service>")
        return 1
    service = args[0]

    if service in API_ONLY_SERVICES:
        print(f"[WARN] {service}: {API_ONLY_SERVICES[service]}")
        kind = input("Store an api_token instead of password? [Y/n]: ").strip().lower()
        if kind != "n":
            token = getpass.getpass(f"{service} API token: ")
            Vault().set_token(service, token)
            print(f"Saved api_token for {service}.")
            return 0

    username = input(f"{service} username/email: ").strip()
    password = getpass.getpass(f"{service} password: ")
    Vault().set_password(service, username, password)
    print(f"Saved password credentials for {service}.")
    return 0


def cmd_list(args):
    rows = Vault().list_services()
    if not rows:
        print("Vault is empty.")
        return 0
    print(f"{'service':<20} {'kind':<12}")
    print("-" * 32)
    for service, kind in rows:
        print(f"{service:<20} {kind:<12}")
    return 0


def cmd_delete(args):
    if not args:
        print("Usage: delete <service>")
        return 1
    Vault().delete(args[0])
    print(f"Deleted {args[0]}.")
    return 0


def cmd_open(args):
    if not args:
        print("Usage: open <service> [goal]")
        return 1
    service = args[0].lower()
    goal = args[1] if len(args) > 1 else None

    if service in API_ONLY_SERVICES:
        print(f"[BLOCKED] {service}: {API_ONLY_SERVICES[service]}")
        print("Use the API adapter instead (TODO: wire API clients per service).")
        return 2

    if service == "amazon_kdp":
        amazon_kdp.open_kdp(goal=goal or "bookshelf")
        return 0

    # Fall through to generic browser adapter
    generic.open_service(service, goto=None)
    return 0


def cmd_google(args):
    """
    Google OAuth + diagnostics:
      google auth          — run OAuth consent flow, save token to vault
      google whoami        — print the authenticated Google account email/profile
      google reauth        — force a new consent flow (e.g. if scopes changed)
    """
    sub = (args[0] if args else "auth").lower()
    if sub == "auth":
        google_adapter.authorize()
        return 0
    if sub == "reauth":
        google_adapter.authorize(force=True)
        return 0
    if sub == "whoami":
        info = google_adapter.whoami()
        print(f"email:   {info.get('email')}")
        print(f"name:    {info.get('name')}")
        print(f"picture: {info.get('picture')}")
        return 0
    print("Usage: google {auth|reauth|whoami}")
    return 1


def cmd_x(args):
    """
    X (Twitter) commands:
      x whoami                      — show authenticated account
      x post "<text>"               — publish a tweet
      x mentions [N]                — show N recent mentions (default 10)
    """
    sub = (args[0] if args else "whoami").lower()
    if sub == "whoami":
        info = x_twitter.whoami()
        print(f"@{info['username']}  ({info['name']})")
        print(f"followers: {info['followers']}   tweets: {info['tweets']}")
        return 0
    if sub == "post":
        text = " ".join(args[1:])
        if not text:
            print("Usage: x post \"<text>\"")
            return 1
        r = x_twitter.post_tweet(text)
        print(f"Posted: {r['url']}")
        return 0
    if sub == "mentions":
        n = int(args[1]) if len(args) > 1 else 10
        for m in x_twitter.list_mentions(max_results=n):
            print(f"  @{m['author']}: {m['text'][:80]}")
        return 0
    print("Usage: x {whoami|post|mentions}")
    return 1


def cmd_meta(args):
    """
    Meta (Facebook + Instagram) commands:
      meta whoami                  — show Page + IG identity
      meta fb post "<text>"        — publish a text post to the FB Page
      meta ig recent [N]           — list recent IG posts
    """
    sub = (args[0] if args else "whoami").lower()
    if sub == "whoami":
        info = meta.whoami()
        fb, ig = info["facebook"], info["instagram"]
        print(f"FB: {fb['name']}   followers={fb['followers']}")
        print(f"IG: @{ig['username']}   followers={ig['followers']}   posts={ig['media']}")
        return 0
    if sub == "fb" and len(args) >= 2 and args[1].lower() == "post":
        text = " ".join(args[2:])
        if not text:
            print("Usage: meta fb post \"<text>\"")
            return 1
        r = meta.fb_post_text(text)
        print(f"Posted: {r}")
        return 0
    if sub == "ig" and len(args) >= 2 and args[1].lower() == "recent":
        n = int(args[2]) if len(args) > 2 else 10
        for m in meta.ig_recent_media(limit=n):
            print(f"  • {(m.get('caption','') or '(no caption)')[:60]}  →  {m.get('permalink','')}")
        return 0
    print("Usage: meta {whoami | fb post \"...\" | ig recent [N]}")
    return 1


def cmd_canva(args):
    """
    Canva commands:
      canva whoami              — show authenticated Canva user
      canva designs             — list recent designs
    """
    sub = (args[0] if args else "whoami").lower()
    if sub == "whoami":
        me = canva_adapter.whoami()
        print(f"user_id: {me.get('user_id')}   team_id: {me.get('team_id')}")
        return 0
    if sub == "designs":
        for d in canva_adapter.list_designs(limit=20):
            print(f"  {d.get('id','?'):<25}  {d.get('title','(untitled)')}")
        return 0
    print("Usage: canva {whoami|designs}")
    return 1


def cmd_linkedin(args):
    """
    LinkedIn commands:
      linkedin whoami                    — show authenticated member
      linkedin post "<text>"             — post as user
      linkedin post-org "<text>"         — post as company page
    """
    sub = (args[0] if args else "whoami").lower()
    if sub == "whoami":
        me = linkedin_adapter.whoami()
        print(f"{me['name']}  ({me['email']})")
        print(f"person: {me['person_urn']}")
        if me["org_urn"]:
            print(f"org:    {me['org_urn']}")
        return 0
    if sub in ("post", "post-org"):
        text = " ".join(args[1:])
        if not text:
            print("Usage: linkedin post \"<text>\"")
            return 1
        r = linkedin_adapter.post_text(text, as_org=(sub == "post-org"))
        print(f"Posted: urn={r['urn']}")
        return 0
    print("Usage: linkedin {whoami|post|post-org}")
    return 1


def cmd_tiktok(args):
    """
    TikTok commands:
      tiktok whoami              — show authenticated user
      tiktok refresh             — force refresh the access token
    """
    sub = (args[0] if args else "whoami").lower()
    if sub == "whoami":
        me = tiktok_adapter.whoami()
        print(f"@{me.get('username','?')}  ({me.get('display_name','?')})")
        print(f"followers: {me.get('follower_count')}   videos: {me.get('video_count')}   likes: {me.get('likes_count')}")
        print(f"open_id: {me.get('open_id')}")
        return 0
    if sub == "refresh":
        new_tok = tiktok_adapter._refresh_token_if_needed()
        print(f"Refreshed. New access_token first 12 chars: {new_tok[:12]}...")
        return 0
    print("Usage: tiktok {whoami|refresh}")
    return 1


def godmode(command: str) -> int:
    """NarAI entry point. Parse a natural-ish command and dispatch."""
    tokens = command.strip().split()
    if not tokens:
        print("Empty command.")
        return 1
    verb = tokens[0].lower()
    dispatch = {
        "set": cmd_set,
        "list": cmd_list,
        "delete": cmd_delete,
        "rm": cmd_delete,
        "open": cmd_open,
        "google": cmd_google,
        "x": cmd_x,
        "twitter": cmd_x,
        "meta": cmd_meta,
        "facebook": cmd_meta,
        "fb": cmd_meta,
        "instagram": cmd_meta,
        "ig": cmd_meta,
        "canva": cmd_canva,
        "linkedin": cmd_linkedin,
        "li": cmd_linkedin,
        "tiktok": cmd_tiktok,
        "tt": cmd_tiktok,
    }
    fn = dispatch.get(verb)
    if not fn:
        print(f"Unknown command: {verb}")
        print("Verbs: set | list | delete | open")
        return 1
    return fn(tokens[1:])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(godmode(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
