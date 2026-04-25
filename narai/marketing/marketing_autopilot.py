#!/usr/bin/env python3
"""
marketing_autopilot.py — NarAI Marketing Autopilot
30-day launch engine for "AI for Traders & Creators"
Amazon KDP + Gumroad/Etsy/Shopify/Payhip + IG/FB growth
"""
import argparse
import asyncio
import json
import logging
import os
import re
import smtplib
import sqlite3
import sys
import threading
import time
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

_TOKEN_LOG = Path(__file__).resolve().parents[2] / "data" / "token_usage.json"
_DAILY_BUDGET = float(os.getenv("ANTHROPIC_DAILY_BUDGET_USD", "2.50"))


def _today_anthropic_spend() -> float:
    try:
        if not _TOKEN_LOG.exists():
            return 0.0
        records = json.loads(_TOKEN_LOG.read_text())
        today = datetime.now().strftime("%Y-%m-%d")
        total = 0.0
        for r in records:
            if r.get("provider") != "anthropic" or not r.get("ts", "").startswith(today):
                continue
            inp, out = r.get("prompt_tokens", 0), r.get("completion_tokens", 0)
            if "haiku" in r.get("model", ""):
                total += (inp / 1_000_000 * 0.80) + (out / 1_000_000 * 4.0)
            else:
                total += (inp / 1_000_000 * 3.0) + (out / 1_000_000 * 15.0)
        return total
    except Exception:
        return 0.0


def _log_usage(model: str, inp: int, out: int) -> None:
    try:
        _TOKEN_LOG.parent.mkdir(parents=True, exist_ok=True)
        records = json.loads(_TOKEN_LOG.read_text()) if _TOKEN_LOG.exists() else []
        records.append({"ts": datetime.now().isoformat(), "provider": "anthropic",
                        "model": model, "prompt_tokens": inp, "completion_tokens": out,
                        "bot": "marketing_autopilot"})
        if len(records) > 5000:
            records = records[-5000:]
        _TOKEN_LOG.write_text(json.dumps(records, indent=2))
    except Exception:
        pass

# ── Media pipeline (lazy import — graceful if Pillow/ffmpeg not installed) ───
_MEDIA_ROOT = Path(__file__).resolve().parents[2]
import sys as _sys
if str(_MEDIA_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_MEDIA_ROOT))

try:
    from narai_godmode.media.image_composer import compose_post as _compose_post
    from narai_godmode.media.video_composer import (
        ValidationError as _ValidationError,
        ensure_audio_track as _ensure_audio_track,
        validate_before_publish as _validate_before_publish,
    )
    _MEDIA_PIPELINE_AVAILABLE = True
except ImportError:
    _MEDIA_PIPELINE_AVAILABLE = False

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

(BASE_DIR / "output").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / "logs" / "autopilot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("autopilot")


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class StateStore:
    def __init__(self, db_path: Path = BASE_DIR / "autopilot.db"):
        self._db_path = str(db_path)
        self._lock = threading.Lock()

    def _connect(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self._lock:
            conn = self._connect()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    day        INTEGER NOT NULL,
                    type       TEXT NOT NULL,
                    slug       TEXT UNIQUE NOT NULL,
                    payload    TEXT NOT NULL DEFAULT '{}',
                    status     TEXT NOT NULL DEFAULT 'pending',
                    output     TEXT,
                    error      TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    source      TEXT NOT NULL,
                    metric      TEXT NOT NULL,
                    value       REAL NOT NULL,
                    captured_at TEXT NOT NULL
                );
            """)
            conn.commit()
            conn.close()

    def upsert_task(self, day: int, type_: str, slug: str, payload: dict) -> bool:
        now = datetime.utcnow().isoformat()
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT OR IGNORE INTO tasks (day, type, slug, payload, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (day, type_, slug, json.dumps(payload), now, now)
            )
            inserted = cur.rowcount > 0
            conn.commit()
            conn.close()
        return inserted

    def get_all_tasks(self) -> List[Dict]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute("SELECT * FROM tasks ORDER BY day, id").fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def get_tasks_for_day(self, day: int, status: Optional[str] = "pending") -> List[Dict]:
        with self._lock:
            conn = self._connect()
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE day = ? ORDER BY id", (day,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE day = ? AND status = ? ORDER BY id",
                    (day, status)
                ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> Optional[Dict]:
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            conn.close()
        return dict(row) if row else None

    def update_task_status(
        self,
        task_id: int,
        status: str,
        output: Optional[Any] = None,
        error: Optional[str] = None,
    ):
        now = datetime.utcnow().isoformat()
        out_text = json.dumps(output) if output is not None else None
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE tasks SET status=?, output=?, error=?, updated_at=? WHERE id=?",
                (status, out_text, error, now, task_id)
            )
            conn.commit()
            conn.close()

    def log_metric(self, source: str, metric: str, value: float):
        now = datetime.utcnow().isoformat()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO metrics (source, metric, value, captured_at) VALUES (?, ?, ?, ?)",
                (source, metric, value, now)
            )
            conn.commit()
            conn.close()


# ---------------------------------------------------------------------------
# ContentGenerator
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a copywriter for Jhon Wheeler, author of "AI for Traders & Creators".

Style rules:
- Dark, natural, casual tone
- Short sentences. Active voice.
- Write like a human who's been in the game, not a marketer
- No hype. No fluff. Just the truth, sharp and direct.

BANNED words — never use these: assure, crucial, vital, unveil, journey, dive, world, discover, unlock, reveal, elevate, landscape, navigate, tapestry, style, "more than just", "stand out", contrast, improvement

Output format: Return ONLY valid JSON. No markdown. No code fences. No explanation. Pure JSON object."""


class ContentGenerator:
    def __init__(self):
        self._client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        self._model = os.getenv("MARKETING_CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    def _parse_json(self, raw: str) -> dict:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"(\{[\s\S]*\})", cleaned)
            if match:
                return json.loads(match.group(1))
            raise

    async def _call(self, user_prompt: str) -> dict:
        spend = _today_anthropic_spend()
        if spend >= _DAILY_BUDGET:
            raise RuntimeError(
                f"Daily Anthropic budget (${_DAILY_BUDGET:.2f}) reached "
                f"(spent ${spend:.4f}) — marketing_autopilot call blocked"
            )
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        _log_usage(self._model,
                   resp.usage.input_tokens,
                   resp.usage.output_tokens)
        return self._parse_json(resp.content[0].text)

    async def reel_script(self, topic: str, hook: str) -> dict:
        prompt = f"""Write a short-form video reel script for Instagram/TikTok.

Topic: {topic}
Opening hook: {hook}

Return JSON:
{{
  "hook": "the first line spoken on screen",
  "script_lines": ["line 1", "line 2", "..."],
  "cta": "closing call to action",
  "estimated_duration_sec": 30
}}"""
        return await self._call(prompt)

    async def carousel(self, topic: str, slides: int) -> dict:
        prompt = f"""Write a {slides}-slide carousel post for Instagram.

Topic: {topic}

Return JSON:
{{
  "title": "carousel title / hook slide text",
  "slides": [{{"headline": "...", "body": "..."}}],
  "cta": "last slide call to action"
}}"""
        return await self._call(prompt)

    async def email(self, purpose: str, context: str) -> dict:
        prompt = f"""Write a marketing email.

Purpose: {purpose}
Context: {context}

The email is from Jhon Wheeler, author of "AI for Traders & Creators".
Keep it short. Real talk. No fluff.

Return JSON:
{{
  "subject": "email subject line",
  "preview_text": "preview/preheader text (max 90 chars)",
  "body_html": "<p>email body in HTML paragraphs</p>",
  "cta": "button text / closing CTA"
}}"""
        return await self._call(prompt)

    async def ad_copy(self, product: str, angle: str) -> dict:
        prompt = f"""Write paid ad copy for Facebook/Instagram.

Product: {product}
Angle: {angle}

Return JSON:
{{
  "headline": "ad headline (max 40 chars)",
  "primary_text": "main ad body (2-3 short paragraphs)",
  "description": "link description (max 30 chars)",
  "cta": "button text e.g. Shop Now, Learn More"
}}"""
        return await self._call(prompt)

    async def amazon_keywords(self, title: str, niche: str) -> dict:
        prompt = f"""Generate Amazon KDP keyword research for this book.

Title: {title}
Niche: {niche}

Return JSON:
{{
  "keywords": ["keyword 1", "keyword 2", "..."],
  "backend_keywords": "space-separated backend search terms string (max 250 chars)",
  "categories": ["Amazon category path 1", "Amazon category path 2"]
}}

Provide exactly 7 main keywords and 2 category paths."""
        return await self._call(prompt)


# ---------------------------------------------------------------------------
# MetaConnector
# ---------------------------------------------------------------------------

class MetaConnector:
    GRAPH_BASE = "https://graph.facebook.com/v21.0"

    def __init__(self):
        self._ig_token = os.getenv("INSTAGRAM_PAGE_TOKEN", "")
        self._ig_account = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
        self._fb_token = os.getenv("FACEBOOK_PAGE_TOKEN", "")
        self._fb_page = os.getenv("FACEBOOK_PAGE_ID", "")
        self._configured = bool(self._ig_token and self._ig_account)
        self._log = logging.getLogger("meta")

    def _stub(self, method: str):
        self._log.warning(f"MetaConnector not configured — skipping {method}")
        return None

    def post_ig_image(self, image_url: str, caption: str) -> Optional[Dict]:
        if not self._configured:
            return self._stub("post_ig_image")
        try:
            r = httpx.post(
                f"{self.GRAPH_BASE}/{self._ig_account}/media",
                params={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": self._ig_token,
                },
                timeout=30,
            )
            r.raise_for_status()
            container_id = r.json()["id"]
            pub = httpx.post(
                f"{self.GRAPH_BASE}/{self._ig_account}/media_publish",
                params={"creation_id": container_id, "access_token": self._ig_token},
                timeout=30,
            )
            pub.raise_for_status()
            return pub.json()
        except Exception as e:
            self._log.error(f"IG post failed: {e}")
            return None

    def post_fb(self, message: str, link: Optional[str] = None) -> Optional[Dict]:
        if not (self._fb_token and self._fb_page):
            return self._stub("post_fb")
        try:
            params: Dict[str, Any] = {"message": message, "access_token": self._fb_token}
            if link:
                params["link"] = link
            r = httpx.post(f"{self.GRAPH_BASE}/{self._fb_page}/feed", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._log.error(f"FB post failed: {e}")
            return None

    def fetch_insights(self, metric: str) -> Optional[Dict]:
        if not self._configured:
            return self._stub("fetch_insights")
        try:
            r = httpx.get(
                f"{self.GRAPH_BASE}/{self._ig_account}/insights",
                params={"metric": metric, "period": "day", "access_token": self._ig_token},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._log.error(f"Insights fetch failed: {e}")
            return None


# ---------------------------------------------------------------------------
# GumroadConnector
# ---------------------------------------------------------------------------

class GumroadConnector:
    def __init__(self):
        self._token = os.getenv("GUMROAD_ACCESS_TOKEN", "")
        self._log = logging.getLogger("gumroad")

    def list_sales(self, limit: int = 10) -> List[Dict]:
        if not self._token:
            self._log.warning("GumroadConnector not configured — skipping list_sales")
            return []
        try:
            r = httpx.get(
                "https://api.gumroad.com/v2/sales",
                params={"access_token": self._token, "page": 1},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("sales", [])[:limit]
        except Exception as e:
            self._log.error(f"Gumroad list_sales failed: {e}")
            return []


# ---------------------------------------------------------------------------
# ConvertKitConnector
# ---------------------------------------------------------------------------

class ConvertKitConnector:
    BASE = "https://api.convertkit.com/v3"

    def __init__(self):
        self._key = os.getenv("CONVERTKIT_API_KEY", "")
        self._secret = os.getenv("CONVERTKIT_API_SECRET", "")
        self._log = logging.getLogger("convertkit")

    def create_broadcast(self, subject: str, body: str) -> Dict:
        if not self._secret:
            self._log.warning("ConvertKitConnector not configured — skipping create_broadcast")
            return {}
        try:
            r = httpx.post(
                f"{self.BASE}/broadcasts",
                json={"api_secret": self._secret, "subject": subject, "content": body},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._log.error(f"ConvertKit create_broadcast failed: {e}")
            return {}

    def subscriber_count(self) -> int:
        if not self._secret:
            self._log.warning("ConvertKitConnector not configured — returning 0")
            return 0
        try:
            r = httpx.get(
                f"{self.BASE}/subscribers",
                params={"api_secret": self._secret},
                timeout=30,
            )
            r.raise_for_status()
            return r.json().get("total_subscribers", 0)
        except Exception as e:
            self._log.error(f"ConvertKit subscriber_count failed: {e}")
            return 0


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------

class Notifier:
    def __init__(self):
        self._host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
        self._port = int(os.getenv("EMAIL_PORT", "587"))
        self._user = os.getenv("EMAIL_USER", "")
        self._pwd = os.getenv("EMAIL_PASSWORD", "")
        self._default_to = os.getenv("NOTIFY_EMAIL", "wheelerjhonkevensd@gmail.com")
        self._log = logging.getLogger("notifier")

    def send_digest(self, subject: str, body: str, to: Optional[str] = None):
        recipient = to or self._default_to
        if not self._user or not self._pwd:
            print(f"\n[Notifier STDOUT] {subject}\n{body}\n")
            return
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self._user
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))
            with smtplib.SMTP(self._host, self._port) as server:
                server.starttls()
                server.login(self._user, self._pwd)
                server.send_message(msg)
            self._log.info(f"Digest sent to {recipient}: {subject}")
        except Exception as e:
            self._log.error(f"Email send failed: {e}")
            print(f"\n[Notifier FALLBACK] {subject}\n{body}\n")


# ---------------------------------------------------------------------------
# TaskRunner
# ---------------------------------------------------------------------------

class TaskRunner:
    def __init__(self, store: StateStore):
        self._store = store
        self._gen = ContentGenerator()
        self._meta = MetaConnector()
        self._gumroad = GumroadConnector()
        self._convertkit = ConvertKitConnector()
        self._notifier = Notifier()
        self._auto_post = os.getenv("AUTO_POST", "false").lower() == "true"
        self._log = logging.getLogger("runner")
        self._dispatch = {
            "reel":             self._run_reel,
            "carousel":         self._run_carousel,
            "email":            self._run_email,
            "ad_copy":          self._run_ad_copy,
            "amazon_keywords":  self._run_amazon_keywords,
            "analytics_pull":   self._run_analytics_pull,
            "reminder":         self._run_reminder,
        }

    def _payload(self, task: Dict) -> Dict:
        p = task.get("payload", "{}")
        return json.loads(p) if isinstance(p, str) else (p or {})

    def _save_output(self, slug: str, data: Dict):
        path = BASE_DIR / "output" / f"{slug}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        self._log.info(f"Output saved → output/{slug}.json")

    def _maybe_post(self, task_type: str, result: Dict):
        if not (self._auto_post and self._meta._configured):
            return
        if task_type not in {"reel", "carousel", "ad_copy"}:
            return

        caption  = result.get("hook") or result.get("title") or result.get("headline", "")
        subtext  = result.get("subtext") or result.get("body", "")
        img_url  = result.get("cover_image_url", "")
        visual_p = result.get("visual_prompt") or result.get("image_prompt", "")

        # ── Step 1: compose a clean image with Pillow text overlay ────────────
        local_path: Optional[str] = None
        if _MEDIA_PIPELINE_AVAILABLE and caption:
            try:
                vp = visual_p or f"Cinematic dark financial scene, abstract wealth visualization"
                local_path = _compose_post(
                    visual_prompt=vp,
                    headline=caption,
                    subtext=subtext[:120] if subtext else None,
                )
                self._log.info(f"[Media] Composed post image → {local_path}")
            except Exception as exc:
                self._log.warning(f"[Media] compose_post failed: {exc} — falling back to cover_image_url")

        # ── Step 2: validate asset before publish ─────────────────────────────
        if local_path and _MEDIA_PIPELINE_AVAILABLE:
            try:
                _validate_before_publish(local_path)
            except _ValidationError as exc:
                self._log.error(f"[Media] Validation failed — skipping post: {exc}")
                return

        # ── Step 3: publish — prefer local composed image, fall back to URL ──
        if local_path:
            cdn_base = os.getenv("MEDIA_CDN_URL", "")
            if cdn_base:
                fname = Path(local_path).name
                img_url = f"{cdn_base.rstrip('/')}/{fname}"
                self._log.info(f"[Media] Using CDN URL → {img_url}")
            else:
                # Surface this loudly — silent skips here mean lost reach.
                self._log.warning(
                    f"[Media][skip] reason=cdn_url_missing local_path={local_path} "
                    "fix=set MEDIA_CDN_URL env var so Meta Graph API can fetch the image"
                )

        if img_url:
            self._meta.post_ig_image(img_url, caption)
        else:
            reason = "cdn_url_missing" if local_path else "no_local_path_and_no_cover_url"
            self._log.warning(f"[Media][skip] reason={reason} task_type={task_type}")

    def run(self, task: Dict) -> Dict:
        type_ = task.get("type", "")
        handler = self._dispatch.get(type_)
        if not handler:
            err = f"Unknown task type: {type_}"
            self._store.update_task_status(task["id"], "failed", error=err)
            return {"error": err}
        return handler(task)

    def _run_reel(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            result = asyncio.run(self._gen.reel_script(
                topic=p.get("topic", "AI for Traders & Creators"),
                hook=p.get("hook", ""),
            ))
            self._save_output(task["slug"], result)
            self._maybe_post("reel", result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}

    def _run_carousel(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            result = asyncio.run(self._gen.carousel(
                topic=p.get("topic", ""),
                slides=int(p.get("slides", 5)),
            ))
            self._save_output(task["slug"], result)
            self._maybe_post("carousel", result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}

    def _run_email(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            result = asyncio.run(self._gen.email(
                purpose=p.get("purpose", ""),
                context=p.get("context", ""),
            ))
            self._save_output(task["slug"], result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}

    def _run_ad_copy(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            result = asyncio.run(self._gen.ad_copy(
                product=p.get("product", "AI for Traders & Creators"),
                angle=p.get("angle", ""),
            ))
            self._save_output(task["slug"], result)
            self._maybe_post("ad_copy", result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}

    def _run_amazon_keywords(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            result = asyncio.run(self._gen.amazon_keywords(
                title=p.get("title", "AI for Traders & Creators"),
                niche=p.get("niche", ""),
            ))
            self._save_output(task["slug"], result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}

    def _run_analytics_pull(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            sources = p.get("sources", ["gumroad", "convertkit"])
            result: Dict[str, Any] = {"pulled_at": datetime.utcnow().isoformat()}

            if "gumroad" in sources:
                sales = self._gumroad.list_sales(limit=20)
                result["gumroad_sales"] = sales
                self._store.log_metric("gumroad", "recent_sales_count", float(len(sales)))

            if "convertkit" in sources:
                count = self._convertkit.subscriber_count()
                result["convertkit_subscribers"] = count
                self._store.log_metric("convertkit", "subscriber_count", float(count))

            self._save_output(task["slug"], result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}

    def _run_reminder(self, task: Dict) -> Dict:
        try:
            p = self._payload(task)
            text = p.get("text", task["slug"])
            print(f"\n[REMINDER — Day {task['day']}] {text}\n")
            self._notifier.send_digest(
                subject=f"NarAI Reminder — Day {task['day']}",
                body=f"<p><strong>Reminder:</strong> {text}</p>",
            )
            result = {"reminder": text, "day": task["day"]}
            self._save_output(task["slug"], result)
            self._store.update_task_status(task["id"], "done", output=result)
            return result
        except Exception as e:
            self._store.update_task_status(task["id"], "failed", error=str(e))
            self._log.error(f"[{task['slug']}] failed: {e}")
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    def __init__(self):
        self._store = StateStore()
        self._store.init_db()
        self._runner = TaskRunner(self._store)
        self._notifier = Notifier()
        self._log = logging.getLogger("orchestrator")

    def load_schedule(self, yaml_path: Path = BASE_DIR / "schedule.yaml") -> int:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        tasks = data.get("tasks", [])
        loaded = 0
        for t in tasks:
            inserted = self._store.upsert_task(
                day=t["day"],
                type_=t["type"],
                slug=t["slug"],
                payload=t.get("payload", {}),
            )
            if inserted:
                loaded += 1
        self._log.info(f"Schedule loaded: {loaded} new tasks ({len(tasks)} total in yaml)")
        return loaded

    def get_current_day(self) -> int:
        launch_str = os.getenv("LAUNCH_DATE", "2026-05-01")
        try:
            launch = date.fromisoformat(launch_str)
        except ValueError:
            self._log.error(f"Invalid LAUNCH_DATE: {launch_str}, defaulting to day 1")
            return 1
        delta = (date.today() - launch).days + 1
        return max(1, min(30, delta))

    def run_day(self, day: Optional[int] = None) -> List[Dict]:
        target_day = day or self.get_current_day()
        tasks = self._store.get_tasks_for_day(target_day, status="pending")
        self._log.info(f"Running Day {target_day}: {len(tasks)} pending tasks")

        results = []
        for task in tasks:
            self._log.info(f"  → [{task['type']}] {task['slug']}")
            result = self._runner.run(task)
            results.append({"slug": task["slug"], "type": task["type"], "result": result})

        self._send_digest(target_day, results)
        return results

    def _send_digest(self, day: int, results: List[Dict]):
        if not results:
            return
        rows = "".join(
            f"<tr><td>{r['slug']}</td><td>{r['type']}</td>"
            f"<td>{'✓ done' if 'error' not in r['result'] else '✗ ' + r['result']['error']}</td></tr>"
            for r in results
        )
        body = f"""
        <h2>NarAI Marketing Autopilot — Day {day} Digest</h2>
        <table border="1" cellpadding="6" style="border-collapse:collapse">
          <tr><th>Slug</th><th>Type</th><th>Status</th></tr>
          {rows}
        </table>
        <p style="color:#888;font-size:12px">Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</p>
        """
        self._notifier.send_digest(
            subject=f"NarAI Marketing — Day {day} Complete ({len(results)} tasks)",
            body=body,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_status(store: StateStore):
    tasks = store.get_all_tasks()
    if not tasks:
        print("No tasks loaded. Run: python marketing_autopilot.py load")
        return

    try:
        from tabulate import tabulate
        rows = [[t["id"], t["day"], t["type"], t["slug"], t["status"]] for t in tasks]
        print(tabulate(rows, headers=["ID", "Day", "Type", "Slug", "Status"], tablefmt="simple"))
    except ImportError:
        print(f"{'ID':>4}  {'Day':>3}  {'Type':<20}  {'Slug':<45}  Status")
        print("-" * 90)
        for t in tasks:
            print(f"{t['id']:>4}  {t['day']:>3}  {t['type']:<20}  {t['slug']:<45}  {t['status']}")

    counts = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    print(f"\nTotal: {len(tasks)}  |  " + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


def main():
    parser = argparse.ArgumentParser(
        description="NarAI Marketing Autopilot — 30-day launch engine"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("load", help="Load schedule.yaml into DB (idempotent)")
    sub.add_parser("run", help="Run today's pending tasks")
    sub.add_parser("daemon", help="Run every 6 hours indefinitely")
    sub.add_parser("status", help="Print all tasks and their status")

    approve_p = sub.add_parser("approve", help="Approve a task by ID")
    approve_p.add_argument("task_id", type=int, help="Task ID from status output")

    args = parser.parse_args()
    orch = Orchestrator()

    if args.cmd == "load":
        n = orch.load_schedule()
        print(f"Loaded {n} new tasks into DB.")

    elif args.cmd == "run":
        day = orch.get_current_day()
        print(f"Running Day {day} tasks...")
        results = orch.run_day(day)
        print(f"\nDone. {len(results)} tasks processed.")
        for r in results:
            status = "✓" if "error" not in r["result"] else "✗"
            print(f"  {status} [{r['type']}] {r['slug']}")

    elif args.cmd == "daemon":
        print("Daemon started. Running every 6 hours. Ctrl+C to stop.")
        while True:
            try:
                orch.load_schedule()
                day = orch.get_current_day()
                log.info(f"Daemon tick — Day {day}")
                orch.run_day(day)
            except Exception as e:
                log.error(f"Daemon run failed: {e}")
            time.sleep(6 * 3600)

    elif args.cmd == "status":
        _print_status(orch._store)

    elif args.cmd == "approve":
        task = orch._store.get_task(args.task_id)
        if not task:
            print(f"Task {args.task_id} not found.")
            sys.exit(1)
        orch._store.update_task_status(args.task_id, "approved")
        print(f"Task {args.task_id} ({task['slug']}) approved.")
        if os.getenv("AUTO_POST", "false").lower() == "true":
            print("AUTO_POST=true — dispatching task now...")
            result = orch._runner.run(task)
            status = "✓ done" if "error" not in result else f"✗ {result['error']}"
            print(f"Result: {status}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
