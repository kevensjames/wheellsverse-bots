#!/usr/bin/env python3
"""
core/youtube.py
─────────────────────────────────────────────────────────────────────────────
YouTube Data API v3 integration.

Features:
  - Upload videos (MP4) with title, description, tags, thumbnail
  - Auto-generate description with affiliate links from article content
  - Schedule videos for future publish time
  - List recent uploads + get view/like/comment stats
  - Fetch transcript-ready script from script_writer bot outputs

OAuth flow (one-time setup):
  1. Go to console.cloud.google.com → Create project → Enable YouTube Data API v3
  2. Create OAuth 2.0 credentials (Desktop app type)
  3. Download client_secret.json → save to data/youtube_client_secret.json
  4. Run: python -m core.youtube auth
     → Opens browser → Authorize → Saves token to data/youtube_token.json

Credentials in .env:
  YOUTUBE_CLIENT_SECRET_FILE  — path to client_secret.json
                                 (default: data/youtube_client_secret.json)

Video upload workflow (typical):
  1. Bot #48 (script_writer) generates a video script
  2. Use text-to-video service (Pictory, HeyGen, etc.) to produce MP4
  3. Call upload_video(video_path, script_content) — description auto-generated
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("youtube")

TOKEN_FILE = ROOT / "data" / "youtube_token.json"
CLIENT_SECRET_FILE = Path(
    os.getenv("YOUTUBE_CLIENT_SECRET_FILE",
              str(ROOT / "data" / "youtube_client_secret.json"))
)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_credentials():
    """Load or refresh OAuth2 credentials."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError(
            "Google API packages not installed.\n"
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_FILE.exists():
                raise RuntimeError(
                    f"YouTube client secret not found at {CLIENT_SECRET_FILE}.\n"
                    "Download it from console.cloud.google.com → Credentials → OAuth 2.0 Client IDs"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.parent.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        logger.info("YouTube OAuth token saved")

    return creds


def _build_service():
    from googleapiclient.discovery import build
    creds = _get_credentials()
    return build("youtube", "v3", credentials=creds)


# ── Description builder ───────────────────────────────────────────────────────

def _build_description(content: str, title: str = "") -> str:
    """Generate a YouTube description from markdown article content."""
    from urllib.parse import urlparse
    site = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev")
    parsed = urlparse(site)
    site_base = f"{parsed.scheme}://{parsed.netloc}"

    # Extract first 400 chars as summary
    lines = [ln.strip() for ln in content.splitlines()
             if ln.strip() and not ln.startswith("#")]
    summary = " ".join(lines)[:400]

    coinbase = f"{site_base}/go/coinbase"
    robinhood = f"{site_base}/go/robinhood"
    amazon_tag = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")

    desc = f"""{summary}

─────────────────────────────────────────
💰 START EARNING TODAY (Free Resources):

📈 Get a FREE stock on Robinhood → {robinhood}
₿ Earn $10 in FREE Bitcoin on Coinbase → {coinbase}
📚 Best passive income books → https://amzn.to/{amazon_tag}

─────────────────────────────────────────
🌐 More content: {site_base}
📧 Join the newsletter for weekly money moves

#passiveincome #investing #crypto #sidehustle #makemoney #financialfreedom #ai
"""
    return desc.strip()


# ── Main client ───────────────────────────────────────────────────────────────

class YouTubeClient:

    def is_connected(self) -> bool:
        """Check if OAuth token exists and is readable."""
        return TOKEN_FILE.exists() and CLIENT_SECRET_FILE.exists()

    def auth(self):
        """Run OAuth flow interactively. Call once to set up credentials."""
        _get_credentials()
        logger.info("YouTube authentication complete")
        return {"status": "authenticated", "token_file": str(TOKEN_FILE)}

    # ── Upload ────────────────────────────────────────────────────────────────

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        content: str = "",
        tags: Optional[List[str]] = None,
        category_id: str = "22",       # 22 = People & Blogs, 28 = Science & Tech
        privacy: str = "private",      # private | unlisted | public
        thumbnail_path: str = "",
        publish_at: str = "",          # ISO 8601 for scheduled upload
    ) -> Dict:
        """
        Upload a video to YouTube.

        Args:
            video_path:      Path to MP4 file
            title:           Video title (max 100 chars)
            description:     Video description (auto-generated from content if empty)
            content:         Markdown article content (used to auto-build description)
            tags:            List of tags (max 500 chars total)
            category_id:     YouTube category ID
            privacy:         "private", "unlisted", or "public"
            thumbnail_path:  Path to thumbnail image (JPG/PNG)
            publish_at:      Schedule publish time (ISO 8601, e.g. "2026-04-01T10:00:00Z")

        Returns:
            {video_id, url, title, status}
        """
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            raise RuntimeError("Run: pip install google-api-python-client")

        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        title = title[:100]
        desc = description or (
            _build_description(content, title) if content else _build_description("", title)
        )
        default_tags = ["passiveincome", "investing", "crypto", "sidehustle",
                        "makemoney", "financialfreedom", "ai", "wheellsverse"]
        all_tags = list({*(tags or []), *default_tags})

        body: Dict = {
            "snippet": {
                "title": title,
                "description": desc,
                "tags": all_tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        if publish_at and privacy == "private":
            body["status"]["publishAt"] = publish_at
            body["status"]["privacyStatus"] = "private"

        media = MediaFileUpload(str(path), mimetype="video/mp4",
                                resumable=True, chunksize=5 * 1024 * 1024)
        svc = _build_service()

        request = svc.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        # Resumable upload with progress logging
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info(f"YouTube upload: {pct}%")

        video_id = response["id"]
        url = f"https://youtu.be/{video_id}"
        logger.info(f"YouTube upload complete: {url}")

        # Set thumbnail if provided
        if thumbnail_path and Path(thumbnail_path).exists():
            try:
                from googleapiclient.http import MediaFileUpload as MFU
                svc.thumbnails().set(
                    videoId=video_id,
                    media_body=MFU(thumbnail_path),
                ).execute()
                logger.info(f"Thumbnail set for {video_id}")
            except Exception as e:
                logger.warning(f"Thumbnail upload failed: {e}")

        return {
            "video_id": video_id,
            "url": url,
            "title": title,
            "privacy": privacy,
            "status": "uploaded",
        }

    def upload_from_script(self, script_path: str, video_path: str,
                           privacy: str = "private", **kwargs) -> Dict:
        """
        Upload video using a script_writer bot output as the description source.
        script_path: path to .md file from bot #48
        video_path:  path to rendered MP4
        """
        content = Path(script_path).read_text(encoding="utf-8")
        m = re.search(r"^#+\s+(.+)$", content, re.MULTILINE)
        title = (m.group(1) if m else Path(script_path).stem).strip()
        return self.upload_video(
            video_path=video_path,
            title=title,
            content=content,
            privacy=privacy,
            **kwargs,
        )

    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_channel_stats(self) -> Dict:
        """Return channel-level stats: subscribers, views, video count."""
        svc = _build_service()
        resp = svc.channels().list(part="statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return {"error": "No channel found"}
        stats = items[0].get("statistics", {})
        return {
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
        }

    def list_videos(self, limit: int = 10) -> List[Dict]:
        """List recent videos with view/like/comment counts."""
        svc = _build_service()
        search = svc.search().list(
            part="id,snippet", forMine=True, type="video",
            order="date", maxResults=limit,
        ).execute()

        video_ids = [item["id"]["videoId"] for item in search.get("items", [])]
        if not video_ids:
            return []

        details = svc.videos().list(
            part="snippet,statistics",
            id=",".join(video_ids),
        ).execute()

        results = []
        for item in details.get("items", []):
            snip = item.get("snippet", {})
            stats = item.get("statistics", {})
            results.append({
                "video_id": item["id"],
                "title": snip.get("title", ""),
                "url": f"https://youtu.be/{item['id']}",
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "published": snip.get("publishedAt", ""),
            })
        return results

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        if not TOKEN_FILE.exists():
            return {
                "connected": False,
                "reason": (
                    "OAuth not completed. Run: python -m core.youtube auth\n"
                    "First download client_secret.json from console.cloud.google.com"
                ),
            }
        try:
            stats = self.get_channel_stats()
            return {"connected": True, **stats}
        except Exception as e:
            return {"connected": False, "error": str(e)}


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: Optional[YouTubeClient] = None


def get_youtube() -> YouTubeClient:
    global _client
    if _client is None:
        _client = YouTubeClient()
    return _client


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        get_youtube().auth()
        print("YouTube auth complete — token saved to", TOKEN_FILE)
    else:
        print(json.dumps(get_youtube().get_status(), indent=2))
