"""Instantly to the board's lead events: SiteBoost replies, one row per
received email.

For each campaign in BOARD_SITEBOOST_CAMPAIGN_IDS, one after the other, a run
reads the campaign's received emails created from the watermark minus 48 hours
up to the run's own start (core.siteboost_instantly.list_replies: GET
/api/v2/emails, read only, one call per 3.5 seconds at most). The first run
backfills from BOARD_BACKFILL_FROM, midnight in New York, and so does the first
run after the campaign list changes (the source's account_ref records the list
a complete run read), so a campaign added later brings its older replies too.
Each received email is one lead_events row, written with board_ingest_leads:

  external_id    the Instantly email id
  kind           reply; funnel siteboost; channel outreach
  campaign_ref   the campaign id
  occurred_at    when Instantly stored the reply (timestamp_created), the
                 time the read window and the watermark run on, so a day the
                 board called final never changes later; a reply stored late
                 counts on the day it was stored. An email without that time is
                 skipped and the run warns. The email's own time
                 (timestamp_email) is kept in raw
  email          the prospect: the campaign lead, else the sender; never our
                 own mailbox
  is_auto_reply  automatic when Instantly's own flag (is_auto_reply) is 1, OR
                 its Out of Office status (i_status 0) is set, OR a careful
                 look at the subject says so: out of office, automatic reply,
                 auto-reply, autoreply, away from the office, vacation
                 responder, and the common German, French and Spanish forms.
                 Only the words an auto-responder puts in front of the quoted
                 subject ("Automatic reply: Re: ...") are read, so our own
                 subject line, which carries the prospect's company name, and a
                 real reply that mentions an office never count. A bounce (from
                 mailer-daemon, postmaster or a no-reply address, or titled
                 Undeliverable, Delivery Status Notification and the like) is
                 automatic too. A flag of 0 overrules none of these.
  raw            ids, type codes and the two timestamps: never the body, the
                 subject or an address

board_day counts distinct prospects per New York day and leaves automatic
replies out, in SQL, so nothing is merged here beyond the email id. A re-sync
lands on the same rows: the SQL keeps the earliest time, fills what was
missing, and keeps an email automatic once a run has said so.

A run is claimed in job_runs first, so two never overlap. On success the
watermark moves to the run's start minus 5 minutes (never back), and the first
complete run sets measured_from. A failed run keeps the watermark and records
a plain sentence on the source: Instantly refusing the key (401), the plan
(402) or the emails:read scope (403) leaves the board at "not connected" or
"partial" with that note, never 0.

Settings: INSTANTLY_API_KEY (a key with the emails:read scope) and
BOARD_SITEBOOST_CAMPAIGN_IDS (every SiteBoost campaign that can still get
replies, comma-separated). With either missing, the sync does not run.
"""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import siteboost_instantly
from core.board import ledger
from core.board.connectors import stripe_sync
from core.board.ledger import BoardDBError, LeadRow
from core.siteboost_instantly import InstantlyError

log = logging.getLogger("board.instantly_sync")

SOURCE_ID = "instantly"
JOB = "instantly_sync"
FUNNEL = "siteboost"
CHANNEL = "outreach"
KEY_ENV = "INSTANTLY_API_KEY"
CAMPAIGNS_ENV = "BOARD_SITEBOOST_CAMPAIGN_IDS"
OVERLAP = timedelta(hours=48)       # each run re-reads this much before the watermark
LAG = timedelta(minutes=5)          # the watermark trails the run's start by this much

# The counts list_replies keeps, copied into the run's detail.
LISTING_COUNTS = ("pages", "listed", "sent_by_us", "other_campaign", "outside_window", "undated", "no_id",
                  "duplicates")


# ─── configuration ──────────────────────────────────────────────────────────

def _settings() -> tuple[Optional[list[str]], Optional[str]]:
    """(campaign ids, None) when the sync can run, else (None, why not)."""
    if not os.getenv(KEY_ENV, "").strip():
        return None, f"no Instantly key: set {KEY_ENV} (a key with the emails:read scope)"
    if siteboost_instantly.api_key() is None:
        return None, f"{KEY_ENV} is not a usable Instantly API key"
    try:
        campaigns = campaign_ids()
    except ValueError as e:
        return None, str(e)
    if not campaigns:
        return None, (f"no SiteBoost campaigns: set {CAMPAIGNS_ENV} to every SiteBoost campaign id, "
                      "comma-separated")
    return campaigns, None


def campaign_ids() -> list[str]:
    """The SiteBoost campaigns from BOARD_SITEBOOST_CAMPAIGN_IDS: Instantly
    campaign ids (UUIDs) separated by commas (spaces, semicolons and new lines
    work too), lower-cased, in order, each once. [] when unset. An entry that
    is not a campaign id raises ValueError; the message names its position,
    never its value."""
    parts = [p for p in re.split(r"[\s,;]+", os.getenv(CAMPAIGNS_ENV, "")) if p]
    found: list[str] = []
    for n, part in enumerate(parts, 1):
        try:
            cid = siteboost_instantly.campaign_uuid(part)
        except ValueError:
            raise ValueError(f"{CAMPAIGNS_ENV}: entry {n} is not an Instantly campaign id") from None
        if cid not in found:
            found.append(cid)
    return found


def configured() -> Optional[str]:
    """None when the sync can run. Otherwise a short plain reason, for the
    board's "not connected" note: the key is missing or unusable, or the
    campaign list is missing or holds something that is not a campaign id.
    It never quotes a value and makes no call."""
    return _settings()[1]


def campaigns_ref(campaigns: list[str]) -> str:
    """What the instantly source's account_ref records after a complete run:
    the campaigns it read, sorted ('campaigns:<id>,<id>'). While it differs
    from the configured list, a run reads every campaign from
    BOARD_BACKFILL_FROM, so a campaign added to the list later brings its
    older replies too, instead of only the last 48 hours."""
    return "campaigns:" + ",".join(sorted(campaigns))


# ─── automatic replies ──────────────────────────────────────────────────────

# Where the quoted subject starts: an auto-responder writes its words in front
# of it ("Automatic reply: Re: ..."), a person's reply has none ("Re: ...").
_QUOTED = re.compile(r"(?<![\w-])(?:re|aw|sv|vs|antw|rv|r|ref|fw|fwd|wg|tr|enc)\s*(?:\[\d+\])?\s*:",
                     re.IGNORECASE)

_AUTO_WORDS = re.compile("|".join((
    r"\bout[\s-]*of[\s-]*(?:the[\s-]*)?office\b",
    r"\bauto(?:matic|mated)?[\s-]*(?:reply|replies|response|responder|answer)\b",    # autoreply, auto-reply
    r"\bvacation[\s-]*(?:auto[\s-]*)?(?:reply|responder|response|notice|message)\b",
    r"\baway from (?:the |my )?(?:office|desk|e-?mail)\b",
    r"^\W*(?-i:OOO)\b",                                                               # in capitals only
    # German
    r"\babwesenheit\w*", r"\babwesend\b", r"\bautomatische antwort\b",
    r"\bau(?:ß|ss)er (?:haus|hause|büro|buero)\b", r"\bnicht im (?:büro|buero)\b",
    # French
    r"\br[ée]ponse automatique\b", r"\babsente? du bureau\b", r"\babsence du bureau\b",
    r"\bhors du bureau\b", r"\bmessage d['’]absence\b",
    # Spanish
    r"\brespuesta autom[áa]tica\b", r"\bfuera de (?:la )?oficina\b", r"\bausente de la oficina\b",
    r"\bmensaje de ausencia\b",
)), re.IGNORECASE)

_BOUNCE_WORDS = re.compile("|".join((
    r"\bundeliverable\b", r"\bundelivered mail\b", r"\bdelivery status notification\b",
    r"\bmail delivery (?:failed|failure|subsystem)\b", r"\bdelivery (?:has )?failed\b", r"\bdelivery failure\b",
    r"^\W*returned mail\b", r"^\W*failure notice\b", r"\bmessage not delivered\b", r"\bnon-?delivery\b",
    r"\bunzustellbar\b", r"\bnicht zustellbar\b",                     # German
    r"\bnon remis\b", r"\bnon distribuable\b",                         # French
    r"\bno se (?:pudo|puede) entregar\b", r"\bmensaje no entregado\b",  # Spanish
)), re.IGNORECASE)

_MACHINE_SENDER = re.compile(r"(?:mailer[-_]?daemon|mail[-_]?daemon|postmaster|no[-_]?reply|do[-_]?not[-_]?reply)"
                             r"(?:\+[^@]*)?@.+", re.IGNORECASE)


def _own_words(subject) -> str:
    """The words in front of the quoted subject ('Automatic reply: ' in
    'Automatic reply: Re: Jay - quick fix idea'), or the whole subject when
    nothing is quoted."""
    if not isinstance(subject, str):
        return ""
    found = _QUOTED.search(subject)
    return subject[:found.start()] if found else subject


def auto_reply_reason(reply: dict) -> Optional[str]:
    """Why a received email is automatic, or None for a real reply:

      sender         from mailer-daemon, postmaster or a no-reply address
      bounce         titled as a delivery failure (Undeliverable, ...)
      instantly      Instantly's own is_auto_reply flag is 1
      out_of_office  Instantly's Out of Office status (i_status 0)
      subject        the subject check: the auto-responder's own words in
                     front of the quoted subject

    Any one of them is enough, whatever the others say: a flag of 0 does not
    overrule an out-of-office status or an auto-responder's subject. A real
    reply that only mentions an office has none of them."""
    words = _own_words(reply.get("subject"))
    if _MACHINE_SENDER.fullmatch(reply.get("from_address") or ""):
        return "sender"
    if _BOUNCE_WORDS.search(words):
        return "bounce"
    if reply.get("is_auto_reply"):
        return "instantly"
    status = reply.get("i_status")
    if status == 0 and not isinstance(status, bool):
        return "out_of_office"
    if _AUTO_WORDS.search(words):
        return "subject"
    return None


# ─── one received email, one row ────────────────────────────────────────────

def reply_time(reply: dict) -> tuple[Optional[datetime], Optional[str]]:
    """(the time a reply counts at, which of Instantly's times it is): when
    Instantly stored it, timestamp_created. The read window and the watermark
    run on that time too, so a reply Instantly stores late lands on the day it
    was stored, never on a day the board already called final. (None, None)
    without it: the email's own time (timestamp_email) is kept in raw only."""
    stored = reply.get("timestamp_created")
    return (stored, "timestamp_created") if stored is not None else (None, None)


def prospect_email(reply: dict) -> Optional[str]:
    """Who replied: the campaign lead, else the sender, never our own mailbox
    (eaccount). None when neither is known; the board then counts the email
    as one prospect of its own."""
    ours = reply.get("eaccount")
    for candidate in (reply.get("lead"), reply.get("from_address")):
        if candidate and candidate != ours:
            return candidate
    return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def to_row(reply: dict, campaign_id: str) -> Optional[LeadRow]:
    """One received email (a list_replies dict) as a lead_events row; None
    when Instantly gives it no time at all."""
    occurred, time_source = reply_time(reply)
    if occurred is None:
        return None
    reason = auto_reply_reason(reply)
    flag = reply.get("is_auto_reply")
    raw = {"message_id": reply.get("message_id"), "thread_id": reply.get("thread_id"),
           "lead_id": reply.get("lead_id"), "ue_type": reply.get("ue_type"), "i_status": reply.get("i_status"),
           "is_auto_reply": None if flag is None else int(flag), "auto_reply_by": reason,
           "timestamp_email": _iso(reply.get("timestamp_email")),
           "timestamp_created": _iso(reply.get("timestamp_created")), "time_source": time_source}
    return LeadRow(external_id=reply["id"], kind="reply", occurred_at=occurred, email=prospect_email(reply),
                   funnel=FUNNEL, channel=CHANNEL, campaign_ref=campaign_id, is_auto_reply=reason is not None,
                   raw=raw)


def collect(campaigns: list[str], since: datetime, until: datetime) -> tuple[list[LeadRow], dict]:
    """Read every campaign's received emails created in [since, until), one
    campaign after the other, and map them. Returns the rows and the counts
    for the run's detail. Raises InstantlyError when a read fails."""
    rows: list[LeadRow] = []
    seen: set[str] = set()
    listing: Counter = Counter()
    automatic: Counter = Counter()
    by_campaign: dict[str, dict] = {}
    no_time = 0
    for cid in campaigns:
        stats: dict = {}
        replies = siteboost_instantly.list_replies(cid, since, until, stats=stats)
        listing.update({k: stats.get(k, 0) for k in LISTING_COUNTS})
        emails = auto = 0
        for reply in replies:
            if reply["id"] in seen:                 # one email under two campaigns: once
                listing["duplicates"] += 1
                continue
            seen.add(reply["id"])
            row = to_row(reply, cid)
            if row is None:
                no_time += 1
                continue
            rows.append(row)
            emails += 1
            if row.is_auto_reply:
                auto += 1
                automatic[row.raw["auto_reply_by"]] += 1
        by_campaign[cid] = {"emails": emails, "automatic": auto}
    detail = {"campaigns": len(campaigns), **{k: listing.get(k, 0) for k in LISTING_COUNTS},
              "no_time": no_time, "emails": len(rows), "automatic": sum(automatic.values()),
              "automatic_by": dict(automatic), "by_campaign": by_campaign}
    return rows, detail


# ─── one run ────────────────────────────────────────────────────────────────

def _warning(detail: dict) -> Optional[str]:
    """What an ok run must still tell the owner: emails Instantly listed that
    the board could not read, so replies may be missing."""
    n = detail.get("no_id", 0) + detail.get("no_time", 0)
    if not n:
        return None
    return (f"skipped {n} email{'s' if n != 1 else ''} that Instantly listed without "
            f"an id or a time: replies may be missing")


def run(trigger: str = "schedule", days: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """One sync run, claimed in job_runs. `days` widens the window to at least
    the last N days (it never narrows it, so no gap opens behind the watermark).
    Returns the run's fields (status ok, failed, busy or skipped); never raises."""
    started = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: dict = {"id": None, "job": JOB, "source_id": SOURCE_ID, "trigger_kind": trigger,
                 "status": None, "started_at": started.isoformat(), "finished_at": None,
                 "window_start": None, "window_end": None, "covered_until": None,
                 "rows_written": 0, "detail": {}, "error": None}
    campaigns, reason = _settings()
    if reason is not None:
        out.update(status="skipped", error=reason)
        return out
    out["run_key"] = started.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    try:
        run_id = ledger.claim_run(JOB, out["run_key"], trigger, SOURCE_ID)
    except BoardDBError as e:
        log.warning("instantly sync: cannot claim a run (%s)", e)
        out.update(status="failed", error=f"database: {e}")
        return out
    if run_id is None:
        out.update(status="busy", error="another Instantly sync is running")
        return out
    out["id"] = run_id
    detail: dict = {"campaigns": len(campaigns)}
    out["detail"] = detail
    since = until = None
    try:
        src = ledger.source_row(SOURCE_ID)
        if src is None:
            raise BoardDBError("no 'instantly' row in public.sources: apply migration 0002")
        if src.get("enabled") is False:
            ledger.finish_run(run_id, "skipped", detail=detail, error="the instantly source is disabled")
            out.update(status="skipped", error="the instantly source is disabled",
                       finished_at=datetime.now(timezone.utc).isoformat())
            return out
        watermark = ledger.parse_ts(src.get("synced_through"))
        first = watermark is None
        ref = campaigns_ref(campaigns)
        from_backfill = first or src.get("account_ref") != ref      # first run, or the campaign list changed
        since = stripe_sync.backfill_start() if from_backfill else watermark - OVERLAP
        if days:
            since = min(since, started - timedelta(days=days))
        until = started
        detail["from_backfill"] = from_backfill
        rows, counts = collect(campaigns, since, until)
        detail.update(counts)
        result = (ledger.ingest_leads(SOURCE_ID, run_id, rows) if rows
                  else {"received": 0, "inserted": 0, "relabelled": 0})
        detail.update(result)
        if src.get("account_ref") != ref:
            ledger.update_source(SOURCE_ID, account_ref=ref)
        covered = started - LAG
        warning = _warning(detail)
        ledger.finish_run(run_id, "ok", rows_written=result["inserted"], detail=detail, error=warning,
                          window_start=since, window_end=until, covered_until=covered)
        ledger.mark_source_ok(SOURCE_ID, covered, stripe_sync.backfill_from() if first else None,
                              warning=warning)
        out.update(status="ok", rows_written=result["inserted"], error=warning,
                   window_start=_iso(since), window_end=_iso(until), covered_until=_iso(covered),
                   finished_at=datetime.now(timezone.utc).isoformat())
        log.info("instantly sync ok: %s new of %s emails, %s automatic (%s)",
                 result["inserted"], result["received"], detail.get("automatic", 0), trigger)
    except Exception as e:  # noqa: BLE001 — a failed run is recorded, never left running
        if isinstance(e, (InstantlyError, BoardDBError, ValueError)):
            message = str(e)[:300]
        else:
            message = f"unexpected {type(e).__name__}"
            log.exception("instantly sync failed")
        log.warning("instantly sync failed: %s", message)
        for step in (lambda: ledger.finish_run(run_id, "failed", detail=detail, error=message,
                                               window_start=since, window_end=until),
                     lambda: ledger.mark_source_error(SOURCE_ID, message)):
            try:
                step()
            except BoardDBError as db_error:
                log.warning("instantly sync: could not record the failure (%s)", db_error)
        out.update(status="failed", error=message, window_start=_iso(since), window_end=_iso(until),
                   finished_at=datetime.now(timezone.utc).isoformat())
    return out
