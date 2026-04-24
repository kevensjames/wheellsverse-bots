"""
LinkedIn adapter — post as the user or the company page.

Credentials from .env:
  LINKEDIN_ACCESS_TOKEN    — OAuth2 user token (long-lived, ~60 days)
  LINKEDIN_PERSON_URN      — e.g. "urn:li:person:XXXXX" (post as user)
  LINKEDIN_ORG_URN         — e.g. "urn:li:organization:XXXXX" (post as page)
  LINKEDIN_CLIENT_ID/SECRET — for token refresh (optional)

Uses the REST v2 `/ugcPosts` endpoint for sharing. The newer `/posts` (Rest API
on api.linkedin.com) requires the "w_member_social" scope.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests


API_BASE = "https://api.linkedin.com/v2"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass


def _check(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(
            f"LinkedIn adapter: {key} is empty in .env.\n"
            "To set up: create an app at https://www.linkedin.com/developers/apps\n"
            "then fill LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, and run the OAuth flow\n"
            "with scopes 'openid profile email w_member_social'."
        )
    return val


def _headers() -> dict:
    _load_env()
    return {
        "Authorization": f"Bearer {_check('LINKEDIN_ACCESS_TOKEN')}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202411",
        "Content-Type": "application/json",
    }


def _req(method: str, path: str, **kwargs) -> dict:
    url = f"{API_BASE}/{path.lstrip('/')}"
    headers = kwargs.pop("headers", {})
    headers.update(_headers())
    r = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    if not r.ok:
        raise RuntimeError(f"LinkedIn {method} {path} → {r.status_code}: {r.text[:500]}")
    return r.json() if r.text else {}


# ── Public API ───────────────────────────────────────────────────────────────

def whoami() -> dict:
    """Verify creds and return the authenticated member's profile."""
    _load_env()
    r = requests.get(f"{API_BASE}/userinfo", headers=_headers(), timeout=30)
    if not r.ok:
        raise RuntimeError(f"LinkedIn userinfo → {r.status_code}: {r.text[:200]}")
    data = r.json()
    return {
        "sub":    data.get("sub"),
        "name":   data.get("name"),
        "email":  data.get("email"),
        "picture": data.get("picture"),
        "person_urn": _check("LINKEDIN_PERSON_URN"),
        "org_urn":    os.environ.get("LINKEDIN_ORG_URN", ""),
    }


def post_text(text: str, as_org: bool = False, visibility: str = "PUBLIC") -> dict:
    """
    Publish a plain-text post.
    as_org=True  → posts as the company page (LINKEDIN_ORG_URN)
    as_org=False → posts as the user (LINKEDIN_PERSON_URN)
    visibility: 'PUBLIC' or 'CONNECTIONS'
    """
    _load_env()
    actor_urn = _check("LINKEDIN_ORG_URN") if as_org else _check("LINKEDIN_PERSON_URN")
    body = {
        "author": actor_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }
    resp = _req("POST", "ugcPosts", json=body)
    post_urn = resp.get("id", "")
    # Construct a shareable URL if possible (LinkedIn returns the URN, not a URL)
    return {"urn": post_urn, "raw": resp}


def post_link(text: str, link_url: str, link_title: str = "",
              link_description: str = "", as_org: bool = False,
              visibility: str = "PUBLIC") -> dict:
    """Publish a post with a link preview card attached."""
    _load_env()
    actor_urn = _check("LINKEDIN_ORG_URN") if as_org else _check("LINKEDIN_PERSON_URN")
    media: dict[str, Any] = {
        "status": "READY",
        "originalUrl": link_url,
    }
    if link_title:
        media["title"] = {"text": link_title}
    if link_description:
        media["description"] = {"text": link_description}

    body = {
        "author": actor_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "ARTICLE",
                "media": [media],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }
    resp = _req("POST", "ugcPosts", json=body)
    return {"urn": resp.get("id", ""), "raw": resp}
