"""
Google adapter — one OAuth flow, all Google services.

Covers: Gmail, Drive, Calendar, YouTube, Sheets, Docs, Photos, Contacts.

Token lives in the vault as service='google', kind='oauth'. Auto-refreshes
via the refresh_token. NarAI calls `get_service("gmail")` to talk to any API.

Setup (one time):
  1. Go to https://console.cloud.google.com/ → create project (or pick one)
  2. APIs & Services → Library → enable: Gmail, Drive, Calendar, YouTube Data,
     Sheets, Docs, People (Contacts), Photos Library
  3. APIs & Services → Credentials → Create → OAuth client ID → Desktop app
  4. Download the JSON, save it somewhere NarAI can read, e.g.:
     /Volumes/Wheellsverse/wheellsverse_bots/data/google_credentials.json
  5. Add to .env:   GOOGLE_CREDENTIALS_JSON=/path/to/google_credentials.json
  6. Run the authorize flow (opens a browser):
       python -m narai_godmode.cli google auth
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Belt-and-suspenders: some Google scopes (e.g. userinfo.*) cause the server
# to return "openid" in the granted set, which oauthlib treats as a scope
# mismatch. Relaxing the check lets the flow complete even if Google returns
# a slightly different scope set than we requested.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from googleapiclient.discovery import build

from ..vault import Vault


class GoogleReauthRequired(Exception):
    """Raised when the stored refresh_token has been revoked / expired past
    recovery. Caller must restart the OAuth consent flow."""
    pass


# Full scope set — one OAuth grant covers every app NarAI will touch.
# Request broad scopes once so you never have to re-consent.
# NOTE: "openid" is included because Google auto-adds it whenever userinfo.email
# or userinfo.profile is requested. If we don't list it, oauthlib throws a
# "Scope has changed" warning-as-error and kills the flow.
SCOPES = [
    # OpenID (auto-granted by Google alongside userinfo.*)
    "openid",
    # Identity
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    # Gmail — read, modify, send
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    # Drive — full access (upload, read, share, delete)
    "https://www.googleapis.com/auth/drive",
    # Calendar — create/read/update/delete events
    "https://www.googleapis.com/auth/calendar",
    # YouTube — view + manage channel, upload videos
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    # Sheets + Docs
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    # People / Contacts
    "https://www.googleapis.com/auth/contacts",
    # Photos (Library API)
    "https://www.googleapis.com/auth/photoslibrary",
]


# API discovery metadata — (api_name, api_version) per service shortname
SERVICE_REGISTRY = {
    "gmail":    ("gmail", "v1"),
    "drive":    ("drive", "v3"),
    "calendar": ("calendar", "v3"),
    "youtube":  ("youtube", "v3"),
    "sheets":   ("sheets", "v4"),
    "docs":     ("docs", "v1"),
    "people":   ("people", "v1"),
    "photos":   ("photoslibrary", "v1"),
    "oauth2":   ("oauth2", "v2"),
}


def _credentials_json_path() -> Path:
    """Path to the OAuth client credentials.json downloaded from Google Cloud.
    Tries env var first, then several common locations in this repo."""
    env_path = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "data" / "google_credentials.json",
        repo_root / "client_secret.json",          # default Google Console download name
        repo_root / "data" / "client_secret.json",
        repo_root / "data" / "youtube_client_secret.json",  # YOUTUBE_CLIENT_SECRET_FILE default
    ]
    # Also honor YOUTUBE_CLIENT_SECRET_FILE since it's the same kind of file
    yt_env = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    if yt_env:
        candidates.insert(0, Path(yt_env))

    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # return the expected default (error messages will show it)


def _load_creds_from_vault() -> Credentials | None:
    rec = Vault().get("google")
    if not rec or rec.get("kind") != "oauth":
        return None
    token_data = rec.get("extra", {}).get("token")
    if not token_data:
        # Legacy path: token may be at top level
        token_data = rec.get("token")
    if not token_data:
        return None
    return Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)


def _save_creds_to_vault(creds: Credentials) -> None:
    """Persist credentials (incl. refresh_token) to the encrypted vault."""
    v = Vault()
    v._write("google", "oauth", {"extra": {"token": creds.to_json()}})


def authorize(force: bool = False) -> Credentials:
    """
    Run the OAuth consent flow and save the token to the vault.
    Opens a browser locally. After consent, prints the authenticated email.
    """
    creds = None if force else _load_creds_from_vault()

    if creds and creds.valid:
        print(f"[google] Already authorized: token valid.")
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_creds_to_vault(creds)
            print("[google] Refreshed existing token.")
            return creds
        except Exception as e:
            print(f"[google] Refresh failed ({e}) — starting new consent flow.")

    cred_path = _credentials_json_path()
    if not cred_path.exists():
        raise RuntimeError(
            f"Google OAuth client file not found: {cred_path}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials → "
            "OAuth client ID (Desktop app). Save it to that path, or set "
            "GOOGLE_CREDENTIALS_JSON in .env."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
    # port=0 picks an available port; opens the consent browser automatically
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    _save_creds_to_vault(creds)

    # Identify the authenticated account
    try:
        info = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
        print(f"[google] Authorized as {info.get('email')}")
    except Exception:
        print("[google] Authorized (identity lookup failed, token saved anyway).")

    return creds


# ── Web-flow OAuth (FastAPI-served consent, used by NarAI dashboard) ─────────


def _build_web_flow(redirect_uri: str) -> Flow:
    """Build a server-side OAuth Flow from env credentials (Web application).

    Reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from env. Unlike the
    Desktop `authorize()` path, this produces a URL you redirect the user to;
    Google then bounces them back to `redirect_uri` with a `code`.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env "
            "(see .env.example)."
        )
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


def build_authorization_url(redirect_uri: str, state: str | None = None) -> tuple[str, str]:
    """Return (auth_url, state) — redirect the user to auth_url."""
    flow = _build_web_flow(redirect_uri)
    auth_url, flow_state = flow.authorization_url(
        access_type="offline",       # gets refresh_token
        prompt="consent",            # forces refresh_token issuance every time
        state=state,
        include_granted_scopes="true",
    )
    return auth_url, flow_state


def exchange_code(code: str, redirect_uri: str) -> Credentials:
    """Exchange authorization code for Credentials; persist to vault; return."""
    flow = _build_web_flow(redirect_uri)
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_creds_to_vault(creds)
    return creds


def get_service(name: str) -> Any:
    """
    Return a Google API service client for the given short name.
    Names: gmail, drive, calendar, youtube, sheets, docs, people, photos, oauth2
    """
    name = name.lower()
    if name not in SERVICE_REGISTRY:
        raise ValueError(
            f"Unknown Google service: {name}. "
            f"Known: {', '.join(SERVICE_REGISTRY)}"
        )

    creds = _load_creds_from_vault()
    if not creds:
        raise GoogleReauthRequired(
            "No Google OAuth token in vault. Visit /api/google/oauth-url to connect."
        )

    # Refresh on use if expired — layered failure handling (options 1/2/3):
    #   1. Raise GoogleReauthRequired so callers fail loudly (option 1)
    #   2. The API layer catches this and returns a reconnect_required response (option 2)
    #   3. Before raising, emit an alert via core.telegram.notify_error (option 3)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_creds_to_vault(creds)
        except RefreshError as e:
            # Refresh token has been revoked (user disconnected in Google account
            # settings, or 6+ months idle in Testing mode, or project deleted).
            _mark_vault_needs_reconsent(str(e))
            _alert_reauth_required(str(e))
            raise GoogleReauthRequired(
                f"Google refresh token rejected: {e}. Reconnect at /api/google/oauth-url"
            ) from e

    api_name, api_version = SERVICE_REGISTRY[name]
    return build(api_name, api_version, credentials=creds, cache_discovery=False)


# ── Failure-mode helpers (used by get_service when refresh fails) ────────────


def _mark_vault_needs_reconsent(reason: str) -> None:
    """Flag the vault entry so /api/google/status reports reconnect_required."""
    try:
        v = Vault()
        rec = v.get("google") or {}
        # Keep the old token around (in case it's recoverable) but annotate it.
        payload = {
            "extra": rec.get("extra", {}),
            "needs_reconsent": True,
            "reconsent_reason": reason,
        }
        v._write("google", "oauth", payload)
    except Exception:
        # If the vault write itself fails, don't mask the original RefreshError.
        pass


def _alert_reauth_required(reason: str) -> None:
    """Best-effort Telegram/email alert so you know to re-consent.
    Silent if telegram isn't configured — never swallow the upstream error."""
    try:
        from core.telegram import notify_error
        notify_error(bot_name="narai-google-oauth", error=f"Reconnect required: {reason}")
    except Exception:
        pass


def needs_reconsent() -> tuple[bool, str]:
    """Check the flag set by _mark_vault_needs_reconsent. Returns (flag, reason)."""
    rec = Vault().get("google")
    if not rec:
        return True, "No token in vault"
    if rec.get("needs_reconsent"):
        return True, rec.get("reconsent_reason", "Token rejected on last refresh")
    return False, ""


def whoami() -> dict:
    """Return info about the authenticated Google account."""
    svc = get_service("oauth2")
    return svc.userinfo().get().execute()


# ── Convenience wrappers so NarAI can ask simple things ──────────────────────

def send_email(to: str, subject: str, body: str, html: bool = False) -> dict:
    """Send a plain text or HTML email through the user's Gmail account."""
    import base64
    from email.message import EmailMessage

    gmail = get_service("gmail")
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if html:
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return gmail.users().messages().send(userId="me", body={"raw": encoded}).execute()


def list_recent_emails(query: str = "", max_results: int = 10) -> list[dict]:
    """List recent Gmail messages matching the query (Gmail search syntax)."""
    gmail = get_service("gmail")
    resp = gmail.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    ids = [m["id"] for m in resp.get("messages", [])]
    out = []
    for mid in ids:
        m = gmail.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
        out.append({
            "id": mid,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": m.get("snippet", ""),
        })
    return out


def upload_to_drive(local_path: str, mime_type: str = "application/octet-stream",
                    folder_id: str | None = None) -> dict:
    """Upload a local file to Google Drive. Returns the created file metadata."""
    from googleapiclient.http import MediaFileUpload

    drive = get_service("drive")
    metadata = {"name": Path(local_path).name}
    if folder_id:
        metadata["parents"] = [folder_id]
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    return drive.files().create(
        body=metadata, media_body=media, fields="id, name, webViewLink"
    ).execute()


def create_calendar_event(summary: str, start_iso: str, end_iso: str,
                          description: str = "", calendar_id: str = "primary") -> dict:
    """Create a Google Calendar event. Times must be ISO 8601 with timezone."""
    cal = get_service("calendar")
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso},
        "end":   {"dateTime": end_iso},
    }
    return cal.events().insert(calendarId=calendar_id, body=event).execute()


def upload_youtube_video(video_path: str, title: str, description: str = "",
                         tags: list[str] | None = None, privacy: str = "private") -> dict:
    """Upload a video to YouTube. privacy: 'public', 'private', or 'unlisted'."""
    from googleapiclient.http import MediaFileUpload

    yt = get_service("youtube")
    body = {
        "snippet": {"title": title, "description": description, "tags": tags or []},
        "status":  {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
    return response
