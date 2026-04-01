#!/usr/bin/env python3
"""
core/output_automation.py
─────────────────────────────────────────────────────────────────────────────
Output Automation Layer.

Enables bots to automatically:
  • Send emails (SMTP — Gmail/any provider)
  • Post to Slack (webhook)
  • Post to Discord (webhook)
  • Export outputs as PDF, HTML, or plain-text files
  • Publish daily/weekly digest reports
  • Queue and batch multiple outputs before sending

Configuration (via .env):
  EMAIL_USER          — sender address
  EMAIL_PASSWORD      — app password (Gmail: enable 2FA → App Passwords)
  EMAIL_SMTP_HOST     — default: smtp.gmail.com
  EMAIL_SMTP_PORT     — default: 587
  EMAIL_DEFAULT_TO    — default recipient(s), comma-separated
  SLACK_WEBHOOK_URL   — Slack incoming webhook
  DISCORD_WEBHOOK_URL — Discord channel webhook
  REPORT_AUTO_SEND    — "true" to auto-send reports after bots run

All methods are safe — never raise, return {"status": "ok"|"error", ...}
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import smtplib
import threading
import time
from collections import deque
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("output_automation")

LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slug(s: str) -> str:
    return s.lower().replace(" ", "_").replace("/", "_")[:40]


# ─── Email ────────────────────────────────────────────────────────────────────

class EmailSender:
    """
    SMTP email sender — works with Gmail, Outlook, SendGrid relay, etc.
    For Gmail: use an App Password (not your account password).
    """

    def __init__(self):
        self.smtp_host = _env("EMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(_env("EMAIL_SMTP_PORT", "587"))
        self.user = _env("EMAIL_USER")
        self.password = _env("EMAIL_PASSWORD")
        self.default_to = _env("EMAIL_DEFAULT_TO", self.user)

    @property
    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def send(
        self,
        subject: str,
        body: str,
        to: Optional[str] = None,
        html: bool = False,
        attachments: Optional[List[Path]] = None,
    ) -> Dict:
        if not self.is_configured:
            logger.warning("Email not configured — set EMAIL_USER and EMAIL_PASSWORD")
            return {"status": "skipped", "reason": "email not configured"}

        recipients = [r.strip() for r in (to or self.default_to).split(",") if r.strip()]
        if not recipients:
            return {"status": "error", "reason": "no recipients"}

        try:
            msg = MIMEMultipart("alternative" if html else "mixed")
            msg["Subject"] = subject
            msg["From"] = self.user
            msg["To"] = ", ".join(recipients)

            part = MIMEText(body, "html" if html else "plain", "utf-8")
            msg.attach(part)

            # Attachments
            if attachments:
                from email.mime.base import MIMEBase
                from email import encoders
                for path in attachments:
                    if path.exists():
                        with open(path, "rb") as f:
                            mime_base = MIMEBase("application", "octet-stream")
                            mime_base.set_payload(f.read())
                        encoders.encode_base64(mime_base)
                        mime_base.add_header(
                            "Content-Disposition",
                            f'attachment; filename="{path.name}"'
                        )
                        msg.attach(mime_base)

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.user, recipients, msg.as_string())

            logger.info(f"Email sent: '{subject}' → {recipients}")
            return {"status": "ok", "recipients": recipients, "subject": subject}

        except Exception as e:
            logger.error(f"Email failed: {e}")
            return {"status": "error", "reason": str(e)}

    def send_bot_report(self, bot_name: str, content: str, to: Optional[str] = None) -> Dict:
        subject = f"[WheellsVerse] {bot_name} Report — {datetime.now().strftime('%Y-%m-%d')}"
        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:auto">
        <div style="background:#0d0d0d;padding:20px;border-radius:8px;margin-bottom:20px">
          <h2 style="color:#00ffcc;margin:0">WheellsVerse Bot Report</h2>
          <p style="color:#aaa;margin:5px 0">{bot_name} · {_now_str()}</p>
        </div>
        <div style="background:#f9f9f9;padding:20px;border-radius:8px;white-space:pre-wrap">{content}</div>
        <p style="color:#999;font-size:12px;margin-top:20px">
          Sent automatically by the WheellsVerse Bot Ecosystem.
        </p>
        </body></html>
        """
        return self.send(subject, html_body, to=to, html=True)

    def send_digest(self, subject: str, sections: List[Dict], to: Optional[str] = None) -> Dict:
        """Send a multi-section digest email.
        sections: [{"title": "...", "content": "...", "bot": "..."}, ...]
        """
        sections_html = ""
        for sec in sections:
            sections_html += f"""
            <div style="margin-bottom:24px;padding:16px;background:#f9f9f9;border-radius:6px;border-left:4px solid #00ffcc">
              <h3 style="color:#333;margin:0 0 8px">{sec.get('title','')}</h3>
              <p style="color:#666;font-size:12px;margin:0 0 8px">Source: {sec.get('bot','WheellsVerse')}</p>
              <div style="white-space:pre-wrap;color:#444">{sec.get('content','')[:2000]}</div>
            </div>
            """
        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:auto">
        <div style="background:#0d0d0d;padding:20px;border-radius:8px;margin-bottom:20px">
          <h2 style="color:#00ffcc;margin:0">{subject}</h2>
          <p style="color:#aaa;margin:5px 0">{_now_str()} · WheellsVerse Digest</p>
        </div>
        {sections_html}
        <p style="color:#999;font-size:12px;margin-top:20px">
          Auto-generated by WheellsVerse · {len(sections)} sections
        </p>
        </body></html>
        """
        return self.send(subject, html_body, to=to, html=True)


# ─── Slack ────────────────────────────────────────────────────────────────────

class SlackSender:
    """Post messages to a Slack channel via incoming webhook."""

    def __init__(self):
        self.webhook_url = _env("SLACK_WEBHOOK_URL")

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url) and "your/webhook" not in self.webhook_url

    def send(self, text: str, blocks: Optional[List] = None) -> Dict:
        if not self.is_configured:
            return {"status": "skipped", "reason": "SLACK_WEBHOOK_URL not set"}
        payload: Dict[str, Any] = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return {"status": "error", "reason": str(e)}

    def send_bot_result(self, bot_name: str, summary: str, status: str = "success") -> Dict:
        emoji = "✅" if status == "success" else "❌"
        color = "#00ffcc" if status == "success" else "#ff4444"
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {bot_name} Completed"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{_now_str()}*\n\n{summary[:2000]}"},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "WheellsVerse Bot Ecosystem"}],
            },
        ]
        return self.send(f"{emoji} {bot_name}: {summary[:100]}", blocks)

    def send_alert(self, title: str, message: str) -> Dict:
        return self.send(
            f":rotating_light: *{title}*\n{message}",
        )

    def send_daily_summary(self, stats: Dict) -> Dict:
        text = (
            f":robot_face: *WheellsVerse Daily Summary — {datetime.now().strftime('%B %d, %Y')}*\n"
            f"• Bots run: {stats.get('total_runs', 0)}\n"
            f"• Succeeded: {stats.get('succeeded', 0)}\n"
            f"• Failed: {stats.get('failed', 0)}\n"
            f"• Outputs generated: {stats.get('outputs', 0)}"
        )
        return self.send(text)


# ─── Discord ──────────────────────────────────────────────────────────────────

class DiscordSender:
    """Post messages to a Discord channel via webhook."""

    def __init__(self):
        self.webhook_url = _env("DISCORD_WEBHOOK_URL")

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send(self, content: str, username: str = "WheellsVerse", embeds: Optional[List] = None) -> Dict:
        if not self.is_configured:
            return {"status": "skipped", "reason": "DISCORD_WEBHOOK_URL not set"}
        payload: Dict[str, Any] = {
            "username": username,
            "content": content[:2000],
        }
        if embeds:
            payload["embeds"] = embeds
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code == 204:
                return {"status": "ok"}
            resp.raise_for_status()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Discord send failed: {e}")
            return {"status": "error", "reason": str(e)}

    def send_bot_result(self, bot_name: str, summary: str, status: str = "success") -> Dict:
        color = 0x00FFCC if status == "success" else 0xFF4444
        embeds = [{
            "title": f"{'✅' if status == 'success' else '❌'} {bot_name}",
            "description": summary[:2048],
            "color": color,
            "footer": {"text": f"WheellsVerse · {_now_str()}"},
        }]
        return self.send(f"Bot completed: **{bot_name}**", embeds=embeds)

    def send_alert(self, title: str, message: str) -> Dict:
        embeds = [{
            "title": f"🚨 {title}",
            "description": message[:2048],
            "color": 0xFF4444,
            "footer": {"text": f"WheellsVerse · {_now_str()}"},
        }]
        return self.send(f"**Alert:** {title}", embeds=embeds)


# ─── File Exporter ────────────────────────────────────────────────────────────

class FileExporter:
    """Export bot outputs to PDF, HTML, or plain-text files."""

    def export_html(self, title: str, content: str, output_dir: Path, filename: str = "") -> Path:
        """Save content as a styled HTML file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{_slug(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path = output_dir / fname
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 900px; margin: 40px auto;
          padding: 0 20px; color: #333; line-height: 1.7; }}
  h1 {{ color: #0d0d0d; border-bottom: 3px solid #00ffcc; padding-bottom: 10px; }}
  .meta {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
  .content {{ white-space: pre-wrap; background: #f9f9f9; padding: 20px;
              border-radius: 8px; border-left: 4px solid #00ffcc; }}
  footer {{ margin-top: 40px; color: #aaa; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">Generated: {_now_str()} · WheellsVerse Bot Ecosystem</div>
<div class="content">{content}</div>
<footer>WheellsVerse · Automated by AI · {_now_str()}</footer>
</body>
</html>"""
        path.write_text(html, encoding="utf-8")
        logger.info(f"Exported HTML: {path}")
        return path

    def export_pdf(self, title: str, content: str, output_dir: Path, filename: str = "") -> Optional[Path]:
        """Save content as PDF via reportlab (graceful skip if not installed)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{_slug(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        path = output_dir / fname
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib import colors

            doc = SimpleDocTemplate(str(path), pagesize=letter,
                                    leftMargin=inch, rightMargin=inch,
                                    topMargin=inch, bottomMargin=inch)
            styles = getSampleStyleSheet()
            story = []

            # Title
            title_style = ParagraphStyle(
                "Title", parent=styles["Heading1"],
                textColor=colors.HexColor("#0d0d0d"), fontSize=18, spaceAfter=6
            )
            story.append(Paragraph(title, title_style))
            story.append(Paragraph(
                f"Generated: {_now_str()} · WheellsVerse",
                ParagraphStyle("Meta", parent=styles["Normal"],
                               textColor=colors.grey, fontSize=10, spaceAfter=16)
            ))
            story.append(Spacer(1, 12))

            # Body — split on newlines
            body_style = ParagraphStyle(
                "Body", parent=styles["Normal"], fontSize=11, leading=16, spaceAfter=8
            )
            for line in content.split("\n"):
                text = line.strip()
                if text:
                    story.append(Paragraph(text.replace("&", "&amp;").replace("<", "&lt;"), body_style))
                else:
                    story.append(Spacer(1, 8))

            doc.build(story)
            logger.info(f"Exported PDF: {path}")
            return path

        except ImportError:
            logger.warning("reportlab not installed — falling back to HTML export")
            return self.export_html(title, content, output_dir, fname.replace(".pdf", ".html"))
        except Exception as e:
            logger.error(f"PDF export failed: {e}")
            return None

    def export_markdown(self, title: str, content: str, output_dir: Path, filename: str = "") -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{_slug(title)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = output_dir / fname
        md = f"# {title}\n\n*Generated: {_now_str()} · WheellsVerse*\n\n---\n\n{content}\n"
        path.write_text(md, encoding="utf-8")
        logger.info(f"Exported Markdown: {path}")
        return path


# ─── Report Queue ─────────────────────────────────────────────────────────────

class ReportQueue:
    """
    Collects bot outputs during the day and sends a batched digest.
    Thread-safe. Call flush() to send everything queued.
    """

    def __init__(self, max_size: int = 100):
        self._queue: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def add(self, bot_name: str, title: str, content: str, category: str = ""):
        with self._lock:
            self._queue.append({
                "bot": bot_name,
                "title": title,
                "content": content,
                "category": category,
                "timestamp": _now_str(),
            })

    def flush(self, send_email: bool = True, send_slack: bool = True) -> Dict:
        """Send everything in the queue as a digest, then clear."""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()

        if not items:
            return {"status": "empty", "count": 0}

        results = {"count": len(items), "email": None, "slack": None}

        subject = f"WheellsVerse Digest — {len(items)} updates · {datetime.now().strftime('%Y-%m-%d')}"

        if send_email:
            email = EmailSender()
            sections = [{"title": i["title"], "content": i["content"], "bot": i["bot"]} for i in items]
            results["email"] = email.send_digest(subject, sections)

        if send_slack:
            slack = SlackSender()
            summary = f"*{len(items)} bot outputs ready:*\n"
            for item in items[:5]:
                summary += f"• `{item['bot']}`: {item['title']}\n"
            if len(items) > 5:
                summary += f"  _...and {len(items) - 5} more_"
            results["slack"] = slack.send(summary)

        return results

    def size(self) -> int:
        return len(self._queue)

    def get_items(self) -> List[Dict]:
        with self._lock:
            return list(self._queue)


# ─── OutputAutomator ──────────────────────────────────────────────────────────

class OutputAutomator:
    """
    Central automation controller.
    Used by bots and the API to dispatch outputs through all channels.
    """

    def __init__(self):
        self.email = EmailSender()
        self.slack = SlackSender()
        self.discord = DiscordSender()
        self.exporter = FileExporter()
        self.queue = ReportQueue()
        self._delivery_log: List[Dict] = []
        self._lock = threading.Lock()

    def _log_delivery(self, channel: str, status: str, detail: str = ""):
        with self._lock:
            self._delivery_log.append({
                "channel": channel,
                "status": status,
                "detail": detail,
                "timestamp": _now_str(),
            })
            if len(self._delivery_log) > 500:
                self._delivery_log = self._delivery_log[-500:]

    def send_to_all(
        self,
        bot_name: str,
        title: str,
        content: str,
        channels: Optional[List[str]] = None,
        output_dir: Optional[Path] = None,
        export_formats: Optional[List[str]] = None,
    ) -> Dict:
        """
        Send bot output to all configured channels.
        channels: ["email", "slack", "discord", "queue"] — defaults to all
        export_formats: ["html", "pdf", "markdown"] — defaults to ["html"]
        """
        if channels is None:
            channels = ["email", "slack", "discord"]
        if export_formats is None:
            export_formats = ["html"]

        results: Dict[str, Any] = {"bot": bot_name, "title": title, "channels": {}}

        # File exports
        if output_dir and export_formats:
            exported_paths = []
            for fmt in export_formats:
                try:
                    if fmt == "html":
                        p = self.exporter.export_html(title, content, output_dir)
                    elif fmt == "pdf":
                        p = self.exporter.export_pdf(title, content, output_dir)
                    elif fmt == "markdown":
                        p = self.exporter.export_markdown(title, content, output_dir)
                    else:
                        continue
                    if p:
                        exported_paths.append(str(p))
                except Exception as e:
                    logger.error(f"Export {fmt} failed: {e}")
            results["exported_files"] = exported_paths

        # Email
        if "email" in channels:
            result = self.email.send_bot_report(bot_name, content[:5000])
            results["channels"]["email"] = result
            self._log_delivery("email", result["status"], bot_name)

        # Slack
        if "slack" in channels:
            result = self.slack.send_bot_result(bot_name, content[:800])
            results["channels"]["slack"] = result
            self._log_delivery("slack", result["status"], bot_name)

        # Discord
        if "discord" in channels:
            result = self.discord.send_bot_result(bot_name, content[:800])
            results["channels"]["discord"] = result
            self._log_delivery("discord", result["status"], bot_name)

        # Queue for digest
        if "queue" in channels:
            self.queue.add(bot_name, title, content)
            results["channels"]["queue"] = {"status": "queued"}

        return results

    def send_alert(self, title: str, message: str, channels: Optional[List[str]] = None) -> Dict:
        """Broadcast an alert to all notification channels."""
        if channels is None:
            channels = ["slack", "discord", "email"]
        results: Dict[str, Any] = {}

        if "slack" in channels:
            results["slack"] = self.slack.send_alert(title, message)
        if "discord" in channels:
            results["discord"] = self.discord.send_alert(title, message)
        if "email" in channels:
            results["email"] = self.email.send(
                f"[ALERT] {title}",
                f"Alert from WheellsVerse:\n\n{title}\n\n{message}"
            )
        return results

    def flush_digest(self) -> Dict:
        """Flush the report queue as a digest."""
        return self.queue.flush(
            send_email=self.email.is_configured,
            send_slack=self.slack.is_configured,
        )

    def auto_post_content(
        self,
        content: str,
        platform: str = "slack",
        topic: str = "",
    ) -> Dict:
        """Auto-post AI-generated content to a platform."""
        title = topic or "New Content"
        if platform == "slack":
            return self.slack.send(f"*{title}*\n\n{content[:1800]}")
        elif platform == "discord":
            return self.discord.send(content[:2000])
        elif platform == "email":
            return self.email.send(title, content)
        return {"status": "error", "reason": f"Unknown platform: {platform}"}

    def export_report(
        self,
        title: str,
        content: str,
        project_slug: str = "wheellsverse",
        fmt: str = "html",
    ) -> Optional[Path]:
        """Export a report to the project's output directory."""
        output_dir = ROOT / "projects" / project_slug / "outputs" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        if fmt == "pdf":
            return self.exporter.export_pdf(title, content, output_dir)
        elif fmt == "markdown":
            return self.exporter.export_markdown(title, content, output_dir)
        else:
            return self.exporter.export_html(title, content, output_dir)

    def get_delivery_log(self, limit: int = 100) -> List[Dict]:
        with self._lock:
            return self._delivery_log[-limit:]

    def get_status(self) -> Dict:
        return {
            "email_configured": self.email.is_configured,
            "slack_configured": self.slack.is_configured,
            "discord_configured": self.discord.is_configured,
            "queue_size": self.queue.size(),
            "delivery_log_count": len(self._delivery_log),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_automator: Optional[OutputAutomator] = None
_automator_lock = threading.Lock()


def get_automator() -> OutputAutomator:
    global _automator
    if _automator is None:
        with _automator_lock:
            if _automator is None:
                _automator = OutputAutomator()
    return _automator
