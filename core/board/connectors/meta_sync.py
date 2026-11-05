"""Meta ad spend to the board: one row per campaign per ad-account day.

The plan's stop rule (marketing/GLOBAL_PLAN.md:128: stop if the cost per lead
is above $5 after 5 days of spend) needs the Toodle campaigns' spend per day.
Meta reports it per campaign and day through the Marketing API's Insights
(core/meta_ads.py, daily_insights), in the ad account's own days and currency.

A run:

  1. reads the ad account (account_info): its time zone, currency and status.
     Meta's days are the account's days: a row for 1 Nov is 1 Nov in that
     zone, which the board shows next to New York days. Once the spend is
     written, the zone, currency and account id go on the meta_ads source
     (sources.day_tz, currency, account_ref). A new account id is read like a
     first run;
  2. reads Insights at level=campaign, time_increment=1, for today and the 28
     days before it in the account's calendar, since Meta revises a day's
     insights for 28 days (the first run reads 90; `days` widens the window
     and never narrows it; a run after a gap also reads every day since the
     last run), 31 days a call at most, so one call on a usual run;
  3. writes one AdSpendRow per campaign and day: spend parsed from Meta's
     decimal string into integer minor units of the account's currency (never
     a float), impressions, link clicks (inline_link_clicks), Meta's own lead
     count as a cross-check only, and funnel "toodle" for the campaigns listed
     in BOARD_TOODLE_META_CAMPAIGN_IDS. Meta revises recent days, so the last
     pull wins (an upsert on campaign and day). Then every stored day is
     labelled from the list as it is now (ledger.label_spend_funnel), so a
     list set or changed later reaches days no longer read. The run's detail
     records that list (toodle_campaigns): until a complete run has used the
     list the server has now, the board shows no Toodle number. A listed
     campaign with no spend in the days read is a warning, by id, also kept
     in the detail (toodle_campaigns_unseen) for the stop rule. A USD account's
     spend is its own USD; any other currency gets USD from board_fill_fx, run
     right after the upsert, once an ECB rate exists (until then the stop rule
     says check_currency).

On success the watermark (synced_through) moves to the run's start: a day is
final once the run started after that day ended in the account's zone. The
first complete run sets measured_from to its first day, so older days read
"not connected", never $0. Each run is claimed in job_runs first, so two never
overlap.

Meta's rate-limit codes and transient errors are retried by the client (3
times at most, 30 seconds apart at most); then the run fails. A failed run
writes no spend, keeps the watermark, and stores a short plain sentence on the
run and on the source (the board's note), never the token, a URL or Meta's
own text. The run's detail keeps Meta's code, fbtrace_id and words, with the
token and the app secret hidden.

  META_INSIGHTS_TOKEN             a system-user token with ads_read only; else META_ACCESS_TOKEN
  AD_ACCOUNT_ID, FB_AD_ACCOUNT_ID the ad account, with or without act_
  BOARD_TOODLE_META_CAMPAIGN_IDS  the Toodle campaigns' ids, comma-separated. Unset, the spend
                                  is still read, but none of it is Toodle's, and the run warns;
                                  so it does for a listed id with no spend in the days read
  META_GRAPH_VERSION              default v26.0
  META_APP_SECRET                 optional: every read then sends appsecret_proof
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterator, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core import meta_ads
from core.board import ledger
from core.board.ledger import AdSpendRow, BoardDBError
from core.meta_ads import MetaAdsClient, MetaAdsError

log = logging.getLogger("board.meta_sync")

SOURCE_ID = "meta_ads"
JOB = "meta_sync"
FUNNEL = "toodle"
TOKEN_ENVS = ("META_INSIGHTS_TOKEN", "META_ACCESS_TOKEN")
ACCOUNT_ENVS = ("AD_ACCOUNT_ID", "FB_AD_ACCOUNT_ID")
CAMPAIGNS_ENV = "BOARD_TOODLE_META_CAMPAIGN_IDS"
VERSION_ENV = "META_GRAPH_VERSION"
SECRET_ENV = "META_APP_SECRET"

REPULL_DAYS = 29         # a run reads today and the 28 days before it: Meta revises a day for 28 days
FIRST_RUN_DAYS = 90      # the first run reads this many
CALL_DAYS = 31           # days in one Insights call
RETENTION_DAYS = 1123    # Meta keeps Insights for 37 months; older days cannot be read
OLDEST_SERVED = (25, 0)  # the oldest Marketing API version that serves ads calls (November 2026)
ACTIVE_STATUSES = frozenset({1, 8, 9})   # account_status values whose ads can run
_STATUS_WORDS = {2: "disabled", 3: "unpaid", 7: "in a risk review", 100: "closing", 101: "closed"}

# Meta's lead counts. "lead" is every lead, on Meta and on the website; the
# others are its parts. A part is never added to the whole, and the two
# names for leads on Meta are never added together.
LEAD_ALL = "lead"
LEAD_ON_META = ("onsite_conversion.lead_grouped", "leadgen_grouped")
LEAD_PIXEL = "offsite_conversion.fb_pixel_lead"

_INT_MAX = 2 ** 31 - 1
_ACCOUNT_RE = re.compile(r"[0-9]{1,30}")
_CAMPAIGN_RE = re.compile(r"[0-9]{1,30}")
_TZ_RE = re.compile(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+)*")
_DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_AMOUNT_RE = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,6})?")
_COUNT_RE = re.compile(r"[0-9]{1,18}")


class MetaSyncError(Exception):
    """Meta answered in a shape the sync cannot write, or the ad account's
    facts cannot be used. The message is a plain sentence, never Meta's own
    text."""


# ─── configuration ──────────────────────────────────────────────────────────

def _first_set(names) -> Optional[tuple[str, str]]:
    """(value, variable) of the first of `names` that is set, trimmed."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value, name
    return None


def _usable(secret: str, longest: int) -> bool:
    return 0 < len(secret) <= longest and secret.isascii() and secret.isprintable() and " " not in secret


def _quote(text, longest: int = 40) -> str:
    text = "".join(c for c in str(text) if c.isprintable())
    return '"' + (text if len(text) <= longest else text[:longest - 3] + "...") + '"'


def read_token() -> Optional[tuple[str, str]]:
    """(token, the variable it came from): META_INSIGHTS_TOKEN, else
    META_ACCESS_TOKEN. None when neither holds a usable token. A malformed
    META_INSIGHTS_TOKEN never falls back to the token that creates ads."""
    found = _first_set(TOKEN_ENVS)
    return found if found is not None and _usable(found[0], 4096) else None


def ad_account() -> Optional[str]:
    """The ad account's number (AD_ACCOUNT_ID, else FB_AD_ACCOUNT_ID), without
    act_; None when unset or not a number."""
    found = _first_set(ACCOUNT_ENVS)
    if found is None:
        return None
    value = found[0]
    if value[:4].lower() == "act_":
        value = value[4:]
    return value if _ACCOUNT_RE.fullmatch(value) else None


def graph_version() -> str:
    """META_GRAPH_VERSION, else the client's default (v26.0)."""
    return os.getenv(VERSION_ENV, "").strip() or meta_ads.DEFAULT_VERSION


def app_secret() -> Optional[str]:
    """META_APP_SECRET when it is usable as one; None otherwise."""
    secret = os.getenv(SECRET_ENV, "").strip()
    return secret if _usable(secret, 256) else None


def toodle_campaigns() -> tuple[frozenset, list[str]]:
    """BOARD_TOODLE_META_CAMPAIGN_IDS as (campaign ids, warnings). An item that
    is not a campaign id (digits) is ignored with a warning."""
    ids: list[str] = []
    warnings: list[str] = []
    for item in os.getenv(CAMPAIGNS_ENV, "").split(","):
        item = item.strip()
        if not item:
            continue
        if _CAMPAIGN_RE.fullmatch(item):
            ids.append(item)
        else:
            shown = _quote(item) if len(item) <= 24 else "a long item"
            warnings.append(f"{CAMPAIGNS_ENV}: {shown} is not a campaign id, so it was ignored")
    return frozenset(ids), warnings


def configured() -> Optional[str]:
    """None when the Meta sync can run. Otherwise why not, in a few plain
    words for the board's note: the source then reads "not connected", never
    $0. Missing Toodle campaign ids do not stop the sync (the run warns)."""
    token = _first_set(TOKEN_ENVS)
    if token is None:
        return "Meta token not set: META_INSIGHTS_TOKEN (or META_ACCESS_TOKEN)"
    if read_token() is None:
        return f"{token[1]} holds spaces or other characters a token cannot have"
    account = _first_set(ACCOUNT_ENVS)
    if account is None:
        return "Meta ad account not set: AD_ACCOUNT_ID (or FB_AD_ACCOUNT_ID)"
    if ad_account() is None:
        return f"{account[1]} is not an ad account number (digits, with or without act_)"
    if not meta_ads.VERSION_RE.fullmatch(graph_version()):
        return f"{VERSION_ENV} must look like {meta_ads.DEFAULT_VERSION}"
    return None


def old_version(version: str) -> Optional[str]:
    """A warning when META_GRAPH_VERSION is older than the oldest version Meta
    serves for ads calls. The call still goes out: Meta may answer it from a
    newer version, or refuse it (code 2635)."""
    m = re.fullmatch(r"v([0-9]{1,3})\.([0-9]{1,2})", version)
    if m and (int(m.group(1)), int(m.group(2))) < OLDEST_SERVED:
        return (f"{VERSION_ENV} is {version}, which Meta no longer serves for ads: "
                f"set it to {meta_ads.DEFAULT_VERSION}")
    return None


# ─── the ad account ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AccountFacts:
    """What the board keeps about the ad account: the zone of its days, its
    currency and its status (1 active)."""
    tz_name: str
    tz: ZoneInfo
    currency: str
    status: Optional[int]


def account_facts(info: dict) -> AccountFacts:
    """The ad account's facts from account_info(). Raises MetaSyncError when
    Meta leaves out the time zone or the currency, or names a zone this
    server does not know."""
    tz_name = info.get("timezone_name")
    tz_name = tz_name.strip() if isinstance(tz_name, str) else ""
    if not tz_name:
        raise MetaSyncError("Meta did not give the ad account's time zone, so its days cannot be read")
    if not _TZ_RE.fullmatch(tz_name) or len(tz_name) > 64:
        raise MetaSyncError("Meta gave the ad account a time zone name the board cannot read")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise MetaSyncError(f"Meta gave the ad account a time zone this server does not know ({tz_name})") from None
    currency = info.get("currency")
    currency = currency.strip().upper() if isinstance(currency, str) else ""
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise MetaSyncError("Meta did not give the ad account's currency, so its spend cannot be read")
    status = info.get("account_status")
    if isinstance(status, str) and _COUNT_RE.fullmatch(status.strip()):
        status = int(status)
    status = status if isinstance(status, int) and not isinstance(status, bool) else None
    return AccountFacts(tz_name=tz_name, tz=tz, currency=currency, status=status)


def status_warning(status: Optional[int]) -> Optional[str]:
    """A warning when the account's ads cannot run (its spend is still read)."""
    if status is None or status in ACTIVE_STATUSES:
        return None
    return f"the ad account is {_STATUS_WORDS.get(status, 'not active')} (status {status}), so its ads cannot run"


def unseen_warning(ids: list[str], since: date) -> str:
    """A warning naming the listed Toodle campaigns that have no spend in the
    days a run read, from `since`: a mistyped id, another account's campaign,
    or one that stopped long ago. Ids only (at most 3), never a name."""
    shown = ", ".join(ids[:3]) + (f" and {len(ids) - 3} more" if len(ids) > 3 else "")
    return (f"no spend seen for campaign{'s' if len(ids) > 1 else ''} {shown} since {since.isoformat()}: "
            f"check {CAMPAIGNS_ENV}")


# ─── the window: which of the account's days a run reads ────────────────────

def window_start(today: date, last_day: Optional[date], days: Optional[int] = None) -> date:
    """The first day a run reads, in the account's calendar; it reads through
    `today`. The first run (no `last_day`) reads FIRST_RUN_DAYS days, a later
    one REPULL_DAYS, and from `last_day` (the account's day when the last
    complete run started) when that is earlier, so no day is left unread after
    a gap. `days` widens it to at least that many days, never narrows it.
    Never earlier than Meta keeps."""
    if last_day is None:
        since = today - timedelta(days=FIRST_RUN_DAYS - 1)
    else:
        since = min(today - timedelta(days=REPULL_DAYS - 1), last_day)
    if isinstance(days, int) and not isinstance(days, bool) and days > 0:
        since = min(since, today - timedelta(days=days - 1))
    return max(since, today - timedelta(days=RETENTION_DAYS - 1))


def call_windows(since: date, until: date, size: int = CALL_DAYS) -> Iterator[tuple[date, date]]:
    """[since, until] in consecutive pieces of at most `size` days."""
    start = since
    while start <= until:
        end = min(until, start + timedelta(days=size - 1))
        yield start, end
        start = end + timedelta(days=1)


# ─── Meta's rows to AdSpendRows ─────────────────────────────────────────────

def _decimal(value) -> Optional[Decimal]:
    """A non-negative decimal from Meta: a string, an int or a Decimal (the
    client parses JSON numbers as Decimal, never float). None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not _AMOUNT_RE.fullmatch(text):
            return None
        value = Decimal(text)
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        return None
    return value


def spend_minor(value, currency: str, where: str) -> tuple[int, bool]:
    """Meta's spend (a decimal string in major units, "12.34") as integer
    minor units of `currency` (1234), and whether it had to be rounded:
    Meta's amounts have the currency's own decimals, so an amount with more
    is rounded half up and counted in the run's detail. A missing spend is 0;
    one that cannot be read raises MetaSyncError."""
    if value is None:
        return 0, False
    amount = _decimal(value)
    if amount is None:
        raise MetaSyncError(f"Meta sent a spend amount the board cannot read for {where}, so nothing was written")
    text = format(amount, "f")
    try:
        return ledger.to_minor_units(text, currency), False
    except ValueError:
        pass
    try:
        exact = amount.scaleb(ledger.currency_exponent(currency))
        return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP)), True
    except InvalidOperation:
        raise MetaSyncError(f"Meta sent a spend amount the board cannot read for {where}, "
                            "so nothing was written") from None


def _count(value, what: str, where: str) -> int:
    """A whole count Meta writes as a string ("1312"); a missing one is 0."""
    if value is None:
        return 0
    if isinstance(value, str) and _COUNT_RE.fullmatch(value.strip()):
        return int(value.strip())
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, Decimal) and value.is_finite() and value >= 0 and value == value.to_integral_value():
        return int(value)
    raise MetaSyncError(f"Meta sent {what} the board cannot read for {where}, so nothing was written")


def _lead_count(value) -> Optional[int]:
    amount = _decimal(value)
    if amount is None:
        return None
    count = int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return count if count <= _INT_MAX else None


def platform_leads(actions) -> Optional[int]:
    """Meta's own count of leads for one campaign-day, from its `actions`:
    "lead" when Meta sends it; otherwise leads on Meta (lead_grouped, else
    leadgen_grouped) plus website leads (fb_pixel_lead). None when Meta sends
    no lead action. A cross-check only: the board counts opt-ins from Kit."""
    if not isinstance(actions, list):
        return None
    values: dict[str, int] = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        kind = action.get("action_type")
        if not isinstance(kind, str) or kind in values:
            continue
        count = _lead_count(action.get("value"))
        if count is not None:
            values[kind] = count
    if LEAD_ALL in values:
        return values[LEAD_ALL]
    on_meta = next((values[k] for k in LEAD_ON_META if k in values), None)
    parts = [n for n in (on_meta, values.get(LEAD_PIXEL)) if n is not None]
    return min(sum(parts), _INT_MAX) if parts else None


def _campaign(value) -> Optional[str]:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= 64 and value.isprintable() else None


def _day(value) -> Optional[date]:
    if not isinstance(value, str) or not _DAY_RE.fullmatch(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _name(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = "".join(c for c in " ".join(value.split()) if c.isprintable())
    return value[:255] or None


def spend_rows(raw: list, currency: str, campaigns: frozenset, since: date,
               until: date) -> tuple[list[AdSpendRow], dict]:
    """One AdSpendRow per campaign and day from daily_insights() rows, and the
    counts for the run's detail. A row that cannot be read fails the whole run
    (MetaSyncError), so a day is never written smaller than Meta has it. A day
    outside [since, until] is left out and counted; a campaign-day Meta lists
    twice is written once (the last)."""
    rows: dict[tuple[str, date], AdSpendRow] = {}
    outside = duplicates = rounded = 0
    for item in raw:
        if not isinstance(item, dict):
            raise MetaSyncError("Meta listed spend in a shape the board cannot read, so nothing was written")
        campaign = _campaign(item.get("campaign_id"))
        if campaign is None:
            raise MetaSyncError("Meta listed spend without a campaign id, so nothing was written")
        day = _day(item.get("date_start"))
        if day is None:
            raise MetaSyncError(f"Meta listed spend for campaign {campaign} without a day, so nothing was written")
        stop = item.get("date_stop")
        if stop is not None and _day(stop) != day:
            raise MetaSyncError(f"Meta listed spend for campaign {campaign} over more than one day, "
                                "so nothing was written")
        if not since <= day <= until:
            outside += 1
            continue
        where = f"campaign {campaign} on {day.isoformat()}"
        sent = item.get("account_currency")
        if sent is not None and (not isinstance(sent, str) or sent.strip().upper() != currency):
            shown = sent.strip().upper() if isinstance(sent, str) and re.fullmatch(r"[A-Za-z]{3}", sent.strip()) \
                else "another currency"
            raise MetaSyncError(f"Meta sent spend in {shown} for an account in {currency} ({where}), "
                                "so nothing was written")
        minor, was_rounded = spend_minor(item.get("spend"), currency, where)
        rounded += was_rounded
        if (campaign, day) in rows:
            duplicates += 1
        rows[(campaign, day)] = AdSpendRow(
            campaign_id=campaign, campaign_name=_name(item.get("campaign_name")),
            funnel=FUNNEL if campaign in campaigns else None, day=day, currency=currency,
            spend_minor=minor, impressions=_count(item.get("impressions"), "impressions", where),
            link_clicks=_count(item.get("inline_link_clicks"), "link clicks", where),
            platform_leads=platform_leads(item.get("actions")))
    out = sorted(rows.values(), key=lambda r: (r.day, r.campaign_id))
    counts: dict = {"rows_read": len(raw), "rows": len(out),
                    "toodle_rows": sum(1 for r in out if r.funnel == FUNNEL),
                    "campaigns": len({r.campaign_id for r in out}),
                    "toodle_campaigns_seen": sorted({r.campaign_id for r in out if r.funnel == FUNNEL})}
    if outside:
        counts["outside_window"] = outside
    if duplicates:
        counts["duplicates"] = duplicates
    if rounded:
        counts["rounded_spend"] = rounded
    return out, counts


# ─── errors: short plain sentences ──────────────────────────────────────────

def failure(e: MetaAdsError, token_name: str, version: str) -> str:
    """A failed read as a short plain sentence for the run and the board's
    note: Meta's code and what to do, never Meta's own text."""
    code = e.code
    tries = f" after {e.retries} retries" if e.retries else ""
    if e.network:
        return f"Meta could not be reached{tries}; the next run tries again"
    if e.throttled:
        named = f"code {code}" if code is not None else f"HTTP {e.status_code}"
        return f"Meta is rate limiting this app or ad account ({named}){tries}; the next run tries again"
    if code == 190:
        return (f"Meta refused the access token (code 190): it is not valid or has expired. "
                f"Make a new token and set {token_name}")
    if code == 2500:
        return f"Meta saw no usable access token (code 2500): check {token_name}"
    if code == 2635:
        return (f"Meta no longer serves API version {version} (code 2635): "
                f"set {VERSION_ENV} to {meta_ads.DEFAULT_VERSION}")
    if code == 100 and e.subcode == 33:
        return ("Meta cannot find the ad account, or the token cannot read it (code 100): "
                "check AD_ACCOUNT_ID and the token's access to the account")
    if code == 100 and "appsecret_proof" in e.meta_message.lower():
        return (f"Meta wants appsecret_proof for this token's app (code 100): "
                f"set {SECRET_ENV} to that app's secret")
    if code in (3, 10) or (code is not None and 200 <= code <= 299):
        return f"Meta refused access (code {code}): the token needs ads_read and access to the ad account"
    if e.too_much_data:
        return "Meta timed out reading one day of spend (code 100); the next run tries again"
    if e.transient:
        named = f" (code {code})" if code is not None else f" (HTTP {e.status_code})" if e.status_code else ""
        return f"Meta had a temporary error{named}{tries}; the next run tries again"
    if code is not None:
        sub = f"/{e.subcode}" if e.subcode is not None else ""
        return f"Meta refused the read (HTTP {e.status_code}, code {code}{sub})"
    if e.status_code == 0:
        return str(e)[:300]          # the client's own sentence: a cursor or a shape it cannot follow
    if e.status_code != 200:
        return f"Meta answered HTTP {e.status_code}"
    return "Meta answered in a shape the board cannot read"


def _meta_error(e: MetaAdsError) -> dict:
    """What the run's detail keeps of a failed read: Meta's code, its trace id
    and its own words, with the token and the app secret hidden."""
    out = {"http": e.status_code, "code": e.code, "subcode": e.subcode, "type": e.error_type,
           "fbtrace_id": e.fbtrace_id, "said": e.meta_message[:200] or None, "retries": e.retries}
    if e.headers:
        out["usage"] = dict(e.headers)
    return {k: v for k, v in out.items() if v not in (None, "", {})}


# ─── one run ────────────────────────────────────────────────────────────────

def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _warning(warnings: list[str]) -> Optional[str]:
    """What an ok run must still tell the owner: the run's error and the
    source's last_error, so the board's note and the morning message show it."""
    text = "; ".join(dict.fromkeys(warnings))
    return (text if len(text) <= 300 else text[:297] + "...") or None


def _client_notes(client: MetaAdsClient, detail: dict, warnings: list[str], version: str) -> None:
    """How the reads went, for the run's detail; a version Meta upgraded
    the calls from is also a warning."""
    detail["requests"] = client.reads
    detail["token_sent_as"] = client.token_sent_as
    detail["appsecret_proof"] = ("dropped: Meta said it is not from the token's app" if client.proof_dropped
                                 else "sent" if client.app_secret else "not set")
    if client.upgraded_to is not None:
        detail["served_version"] = client.upgraded_to or "a newer version"
        if old_version(version) is None:
            warnings.append(f"Meta answered from {client.upgraded_to or 'a newer version'}, not {version}: "
                            f"set {VERSION_ENV} to {meta_ads.DEFAULT_VERSION}")


def run(trigger: str = "schedule", days: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """One sync run, claimed in job_runs. `days` widens the window to at least
    the last N days of the account's calendar (it never narrows it). Returns
    the run's fields (status ok, failed, busy or skipped); never raises."""
    started = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: dict = {"id": None, "job": JOB, "source_id": SOURCE_ID, "trigger_kind": trigger,
                 "status": None, "started_at": started.isoformat(), "finished_at": None,
                 "window_start": None, "window_end": None, "covered_until": None,
                 "rows_written": 0, "detail": {}, "error": None}
    reason = configured()
    if reason is not None:
        out.update(status="skipped", error=reason)
        return out
    token, token_name = read_token()
    account = ad_account()
    version = graph_version()
    campaigns, warnings = toodle_campaigns()
    if not campaigns:
        warnings.append(f"{CAMPAIGNS_ENV} {'names no campaign' if warnings else 'is not set'}, "
                        "so no Meta spend counts as Toodle spend")
    if old_version(version):
        warnings.append(old_version(version))
    out["run_key"] = started.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    try:
        run_id = ledger.claim_run(JOB, out["run_key"], trigger, SOURCE_ID)
    except BoardDBError as e:
        log.warning("meta sync: cannot claim a run (%s)", e)
        out.update(status="failed", error=f"database: {e}")
        return out
    if run_id is None:
        out.update(status="busy", error="another Meta sync is running")
        return out
    out["id"] = run_id
    detail: dict = {"token": token_name, "account": f"act_{account}", "version": version,
                    "toodle_campaigns": sorted(campaigns)}
    out["detail"] = detail
    since = until = window_from = None
    client = MetaAdsClient(access_token=token, ad_account_id=account, version=version, app_secret=app_secret())
    try:
        src = ledger.source_row(SOURCE_ID)
        if src is None:
            raise BoardDBError("no 'meta_ads' row in public.sources: apply migration 0002")
        if src.get("enabled") is False:
            ledger.finish_run(run_id, "skipped", detail=detail, error="the meta_ads source is disabled")
            out.update(status="skipped", error="the meta_ads source is disabled",
                       finished_at=datetime.now(timezone.utc).isoformat())
            return out
        facts = account_facts(client.account_info())
        detail.update(day_tz=facts.tz_name, currency=facts.currency, account_status=facts.status)
        if status_warning(facts.status):
            warnings.append(status_warning(facts.status))
        today = started.astimezone(facts.tz).date()
        watermark = ledger.parse_ts(src.get("synced_through"))
        first = watermark is None
        before = src.get("account_ref")
        changed = bool(before) and before != f"act_{account}"
        if changed:
            shown = before if re.fullmatch(r"act_[0-9]{1,30}", str(before)) else "another account"
            warnings.append(f"the ad account changed from {shown} to act_{account}, "
                            f"so its last {FIRST_RUN_DAYS} days were read")
        last_day = None if (first or changed) else watermark.astimezone(facts.tz).date()
        since = window_start(today, last_day, days)
        until = today
        window_from = datetime.combine(since, dtime(0), facts.tz).astimezone(timezone.utc)
        detail["days"] = {"since": since.isoformat(), "until": until.isoformat(),
                          "count": (until - since).days + 1}
        raw: list = []
        for start, end in call_windows(since, until):
            raw.extend(client.daily_insights(start, end))
        rows, counts = spend_rows(raw, facts.currency, campaigns, since, until)
        detail.update(counts)
        unseen = sorted(campaigns - set(counts["toodle_campaigns_seen"]), key=lambda c: (len(c), c))
        # With toodle_campaigns and days.since, what the board's stop rule repeats on a no_spend verdict.
        detail["toodle_campaigns_unseen"] = unseen
        if unseen:
            warnings.append(unseen_warning(unseen, since))
        written = ledger.upsert_ad_spend(SOURCE_ID, run_id, rows) if rows else 0
        # The funnel is a label: every stored day follows the list as it is
        # now, not only the days just read (a list set or changed later).
        ledger.label_spend_funnel(SOURCE_ID, FUNNEL, campaigns)
        if rows and facts.currency != "USD":
            try:
                detail["fx_converted"] = ledger.fill_fx()
            except BoardDBError as e:
                log.warning("meta sync: board_fill_fx failed (%s)", e)
                warnings.append("the spend was written, but converting it to US dollars failed; "
                                "the next run tries again")
        # Only now, after the spend is written: a new account whose first read
        # fails is still a new account to the next run, which reads it whole.
        ledger.update_source(SOURCE_ID, day_tz=facts.tz_name, currency=facts.currency,
                             account_ref=f"act_{account}")
        _client_notes(client, detail, warnings, version)
        if warnings:
            detail["warnings"] = list(dict.fromkeys(warnings))
        error = _warning(warnings)
        ledger.finish_run(run_id, "ok", rows_written=written, detail=detail, error=error,
                          window_start=window_from, window_end=started, covered_until=started)
        ledger.mark_source_ok(SOURCE_ID, started, since if first else None, warning=error)
        out.update(status="ok", rows_written=written, error=error, window_start=_iso(window_from),
                   window_end=_iso(started), covered_until=_iso(started),
                   finished_at=datetime.now(timezone.utc).isoformat())
        log.info("meta sync ok: %s rows over %s days (%s)", written, detail["days"]["count"], trigger)
    except Exception as e:  # noqa: BLE001 — a failed run is recorded, never left running
        if isinstance(e, MetaAdsError):
            message = failure(e, token_name, version)
            detail["meta_error"] = _meta_error(e)
        elif isinstance(e, (MetaSyncError, BoardDBError, ValueError)):
            message = str(e)[:300]
        else:
            message = f"unexpected {type(e).__name__}"
            log.exception("meta sync failed")
        log.warning("meta sync failed: %s", message)
        _client_notes(client, detail, [], version)
        if warnings:
            detail["warnings"] = list(dict.fromkeys(warnings))
        for step in (lambda: ledger.finish_run(run_id, "failed", detail=detail, error=message,
                                               window_start=window_from, window_end=started if since else None),
                     lambda: ledger.mark_source_error(SOURCE_ID, message)):
            try:
                step()
            except BoardDBError as db_error:
                log.warning("meta sync: could not record the failure (%s)", db_error)
        out.update(status="failed", error=message, window_start=_iso(window_from),
                   window_end=_iso(started) if since else None,
                   finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        client.close()
    return out
