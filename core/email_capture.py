#!/usr/bin/env python3
"""
core/email_capture.py
─────────────────────────────────────────────────────────────────────────────
Email Capture System — collects and stores leads from landing page + forms.

Features:
  • Save leads to CSV + JSON
  • Deduplication by email
  • Lead stats (total, today, by source)
  • Embeddable HTML form snippet
─────────────────────────────────────────────────────────────────────────────
"""

import csv
import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent
LEADS_DIR = ROOT / "data" / "leads"
LEADS_DIR.mkdir(parents=True, exist_ok=True)

LEADS_JSON = LEADS_DIR / "leads.json"
LEADS_CSV = LEADS_DIR / "leads.csv"

logger = logging.getLogger("email_capture")


class EmailCapture:
    """Lead collection and management system."""

    def __init__(self):
        self._lock: threading.Lock = threading.Lock()
        self._leads: List[Dict] = []
        self._emails: set = set()
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if LEADS_JSON.exists():
            try:
                self._leads = json.loads(LEADS_JSON.read_text(encoding="utf-8"))
                self._emails = {ln["email"].lower() for ln in self._leads if "email" in ln}
                logger.info(f"Loaded {len(self._leads)} leads")
            except Exception as e:
                logger.warning(f"Could not load leads: {e}")
                self._leads, self._emails = [], set()

    def _save(self):
        try:
            LEADS_JSON.write_text(json.dumps(self._leads, indent=2), encoding="utf-8")
            with LEADS_CSV.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["email", "name", "source", "topic", "captured_at"]
                )
                writer.writeheader()
                for lead in self._leads:
                    writer.writerow({
                        "email": lead.get("email", ""),
                        "name": lead.get("name", ""),
                        "source": lead.get("source", ""),
                        "topic": lead.get("topic", ""),
                        "captured_at": lead.get("captured_at", ""),
                    })
        except Exception as e:
            logger.error(f"Could not save leads: {e}")

    # ── Capture ───────────────────────────────────────────────────────────────

    def capture(
        self,
        email: str,
        name: str = "",
        source: str = "landing_page",
        topic: str = "",
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Save a new lead. Deduplicates by email.
        Returns {"status": "new"|"duplicate"|"invalid", ...}
        """
        email = email.strip().lower()
        if not email or "@" not in email:
            return {"status": "invalid", "reason": "Invalid email address"}

        with self._lock:
            if email in self._emails:
                return {"status": "duplicate", "email": email}

            lead = {
                "email": email,
                "name": name.strip(),
                "source": source,
                "topic": topic[:80] if topic else "",
                "captured_at": datetime.now().isoformat(),
                "metadata": metadata or {},
            }
            self._leads.insert(0, lead)
            self._emails.add(email)
            self._save()
            logger.info(f"Lead captured: {email} from {source}")
            return {"status": "new", "lead": lead}

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        today = date.today().isoformat()
        today_leads = [ln for ln in self._leads if ln.get("captured_at", "").startswith(today)]
        by_source: Dict[str, int] = {}
        for lead in self._leads:
            src = lead.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1

        return {
            "total_leads": len(self._leads),
            "leads_today": len(today_leads),
            "unique_sources": len(by_source),
            "by_source": by_source,
            "most_recent": self._leads[0] if self._leads else None,
            "files": {
                "json": str(LEADS_JSON.relative_to(ROOT)),
                "csv": str(LEADS_CSV.relative_to(ROOT)),
            },
        }

    def get_leads(self, limit: int = 100, source: str = "") -> List[Dict]:
        leads = self._leads
        if source:
            leads = [ln for ln in leads if ln.get("source") == source]
        return leads[:limit]

    def get_leads_today(self) -> List[Dict]:
        today = date.today().isoformat()
        return [ln for ln in self._leads if ln.get("captured_at", "").startswith(today)]

    # ── Form HTML Snippet ─────────────────────────────────────────────────────

    def generate_form_snippet(
        self,
        action_url: str = "/api/lead",
        cta_text: str = "Get Free Daily Signals",
    ) -> str:
        """Return an embeddable HTML form that POSTs to /api/lead."""
        return f"""<form class="lead-form" onsubmit="submitLead(event)">
  <input type="text"  name="name"  placeholder="Your first name" required>
  <input type="email" name="email" placeholder="Your best email" required>
  <button type="submit">{cta_text}</button>
</form>
<script>
async function submitLead(e) {{
  e.preventDefault();
  const f = e.target;
  const btn = f.querySelector('button');
  btn.textContent = 'Joining...';
  btn.disabled = true;
  try {{
    const r = await fetch('{action_url}', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{name: f.name.value, email: f.email.value, source: 'website'}})
    }});
    const data = await r.json();
    if (['new','duplicate'].includes(data.status)) {{
      f.innerHTML = '<p style="color:#00ff88;font-weight:700;text-align:center;padding:16px">🎉 You\\'re in! Watch your inbox.</p>';
    }} else {{
      btn.textContent = '{cta_text}'; btn.disabled = false;
    }}
  }} catch(err) {{
    btn.textContent = '{cta_text}'; btn.disabled = false;
  }}
}}
</script>"""


# ─── Singleton ────────────────────────────────────────────────────────────────

_capture: Optional[EmailCapture] = None
_cap_lock = threading.Lock()


def get_email_capture() -> EmailCapture:
    global _capture
    if _capture is None:
        with _cap_lock:
            if _capture is None:
                _capture = EmailCapture()
    return _capture
