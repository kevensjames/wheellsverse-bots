"""Kit to the board's leads: Toodle opt-ins, one per subscriber.

A Toodle opt-in is a Kit subscriber who got one of the tags listed in
BOARD_TOODLE_KIT_TAGS. Kit lists the people who hold a tag now, each with
tagged_at, the time the tag was applied (GET /v4/tags/{tag_id}/subscribers).
One subscriber is one opt-in, external_id 'toodle:sub:<subscriber id>', dated
by the earliest of their Toodle tags. The SQL keeps the earliest time across
runs, so a re-run, an overlap and a backfill all land on the same rows.

  BOARD_TOODLE_KIT_TAGS  comma-separated "tag name[:channel]" items, such as
                         "toodle:,meta_ad:meta,meta:meta,blog:organic". Every
                         tag listed marks an opt-in; a channel also labels it.
                         An item splits on its last colon, so a tag name may
                         hold one: end such an item with ":" when it has no
                         channel.
  KIT_API_KEY            Kit's v4 API key. This sync only reads.

The channel is the one of the earliest-tagged tag that has a channel. With
none it is 'unknown', and a later run that sees a channel tag fills it in (the
SQL never replaces a known channel). People who unsubscribed later still
opted in, so the sync asks Kit for every state, not only active people.

A run reads the subscribers tagged from the watermark minus 1 hour up to its
own start. The first run backfills from BOARD_BACKFILL_FROM, midnight in New
York, and sets measured_from to the first New York day it read whole (that
day, unless `days` reached further back). So does a run whose tag set (the
Kit tag ids found for BOARD_TOODLE_KIT_TAGS, with their channels) differs from
the one the last complete run recorded in its job_runs detail: a tag or a
channel added to the setting later then reaches past days too (Kit's volume
is small). Without such a record, a run reads from the watermark as before.
On success the watermark moves to
the run's start minus 10 minutes, so a channel tag applied a moment after the
Toodle tag is read again. Kit's tagged_after and tagged_before filters take
whole days, and Kit does not say whether they are inclusive or which time zone
starts a day, so the sync asks for 2 more days on each side and keeps only the
tag times inside its window.

Kit allows 120 requests a minute per key, shared with the Toodle capture, so
this sync makes at most one request a second. On 429, a Kit server error or no
answer it waits (Kit's Retry-After, else 2, 4 and 8 seconds; 30 at most) and
tries again, 3 times at most, then the run fails. A tag name Kit does not have
is a warning; when no tag is found, the run fails. A subscriber listed without
an id or a tag time fails the run too: a count that cannot be read is never
written as a smaller one. Errors are short plain sentences that may name the
HTTP status, never the key or Kit's own text. The run's detail keeps Kit's
words for a refused query, cut short, with the key and anything like a token
hidden.
"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from core import kit as kit_api
from core.board import ledger
from core.board.connectors.stripe_sync import backfill_start
from core.board.ledger import BoardDBError, LeadRow

log = logging.getLogger("board.kit_sync")

SOURCE_ID = "kit"
JOB = "kit_sync"
FUNNEL = "toodle"
KEY_ENV = "KIT_API_KEY"
TAGS_ENV = "BOARD_TOODLE_KIT_TAGS"
NY = ZoneInfo("America/New_York")
OVERLAP = timedelta(hours=1)        # each run re-reads this much before the watermark
LAG = timedelta(minutes=10)         # the watermark trails the run's start by this much
FILTER_PAD = timedelta(days=2)      # Kit's day filters ask for this much more on each side
FALLBACK_PER_PAGE = 100             # the page size when Kit refuses the first query

_RATE_PER_SEC = 1.0                 # Kit requests a second from one run (tests raise it)
_sleep = time.sleep                 # tests replace it
_RETRIES = 3
_MAX_WAIT = 30.0                    # seconds: the longest wait before a retry
_MAX_PAGES = 1000                   # pages in one list: a guard against a cursor that never ends

_CHANNEL_RE = re.compile(r"[a-z0-9_]{1,32}")
_TOKENISH = re.compile(r"[A-Za-z0-9_+/=-]{24,}")


class KitSyncError(Exception):
    """Kit refused or failed a read, or answered in a shape the sync cannot
    read. The message is a plain sentence that names the HTTP status, never
    the key or Kit's own text. `said` keeps Kit's words for the run's detail."""

    def __init__(self, message: str, status: Optional[int] = None, said: Optional[list] = None):
        super().__init__(message)
        self.status = status
        self.said = said or []
        self.page = 0               # which page of a list failed (0: the first)


# ─── configuration ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TagSpec:
    """One item of BOARD_TOODLE_KIT_TAGS: a Kit tag name and the channel it
    sets (None: it marks the funnel only)."""
    name: str
    channel: Optional[str] = None


def _quote(text, longest: int = 60) -> str:
    text = "".join(c for c in str(text) if c.isprintable())
    return '"' + (text if len(text) <= longest else text[:longest - 3] + "...") + '"'


def tag_specs() -> tuple[list[TagSpec], list[str]]:
    """BOARD_TOODLE_KIT_TAGS as (tags, warnings). Items are comma-separated
    "name[:channel]", split on the last colon and trimmed. A channel must be
    letters, digits or _ (at most 32) once lower-cased; any other is ignored
    with a warning, and its tag still counts. A name listed twice keeps its
    first item."""
    specs: list[TagSpec] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for item in os.getenv(TAGS_ENV, "").split(","):
        item = item.strip()
        if not item:
            continue
        name, colon, channel = item.rpartition(":")
        if not colon:
            name, channel = item, ""
        name, typed = name.strip(), channel.strip()
        channel = typed.lower()
        if not name:
            warnings.append(f"{_quote(item)} names no tag, so it was ignored")
            continue
        if channel and not _CHANNEL_RE.fullmatch(channel):
            warnings.append(f"tag {_quote(name)}: the channel {_quote(typed)} is not letters, "
                            "digits or _, so it was ignored")
            channel = ""
        if name in seen:
            warnings.append(f"tag {_quote(name)} is listed twice; the first is used")
            continue
        seen.add(name)
        specs.append(TagSpec(name, channel or None))
    return specs, warnings


def _usable_key(key: str) -> bool:
    return 0 < len(key) <= 200 and key.isascii() and key.isprintable() and " " not in key


def api_key() -> Optional[str]:
    """KIT_API_KEY, trimmed; None when unset or not usable as a header value."""
    key = os.getenv(KEY_ENV, "").strip()
    return key if _usable_key(key) else None


def configured() -> Optional[str]:
    """None when the Kit sync can run. Otherwise why not, in a few plain words
    for the board's note: the source then reads "not connected", never 0."""
    if not os.getenv(KEY_ENV, "").strip():
        return "Kit key not set: KIT_API_KEY"
    if api_key() is None:
        return "KIT_API_KEY holds spaces or other characters a key cannot have"
    if not os.getenv(TAGS_ENV, "").strip():
        return "Toodle tags not set: BOARD_TOODLE_KIT_TAGS"
    if not tag_specs()[0]:
        return "BOARD_TOODLE_KIT_TAGS names no tag"
    return None


# ─── Kit's API (read only) ──────────────────────────────────────────────────

@dataclass(frozen=True)
class KitTag:
    """A configured tag found in Kit: its id, the name it was configured by,
    and the channel it sets."""
    id: int
    name: str
    channel: Optional[str] = None


def _as_id(value) -> Optional[int]:
    """A Kit id: a positive whole number (a string of digits is accepted)."""
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value.strip()):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _as_time(value) -> Optional[datetime]:
    """Kit's ISO 8601 time (UTC, 'Z'), as an aware datetime; None when unusable.
    A time without an offset is UTC, as Kit writes every time."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _wait(retry_after, attempt: int) -> float:
    """Seconds before retry number attempt + 1: Kit's Retry-After when it
    sends a number, else 2, 4, 8; from 1 to 30."""
    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        seconds = math.nan
    if not math.isfinite(seconds):
        seconds = float(2 ** (attempt + 1))
    return min(max(seconds, 1.0), _MAX_WAIT)


def _kit_said(answer: dict, key: str) -> list[str]:
    """Kit's own error messages, for the run's detail only: at most 3, each
    cut to 120 characters, with the key and anything like a token hidden."""
    said = answer.get("errors")
    if isinstance(said, str):
        said = [said]
    if not isinstance(said, list):
        return []
    out = []
    for item in said[:3]:
        if isinstance(item, list):                  # some endpoints nest them
            item = " ".join(str(x) for x in item)
        text = " ".join(str(item).split())
        if key:
            text = text.replace(key, "[hidden]")
        text = _TOKENISH.sub("[hidden]", text)
        text = "".join(c for c in text if c.isprintable())[:120]
        if text:
            out.append(text)
    return out


def _failure(status, what: str, retried: bool = False) -> str:
    """A refused or failed read as a plain sentence for the run and the board."""
    tries = f" after {_RETRIES} retries" if retried else ""
    if status == 0:
        return f"Kit could not be reached{tries}"
    if status == 401:
        return "Kit refused the API key (HTTP 401): check KIT_API_KEY"
    if status == 403:
        return f"Kit refused access to {what} (HTTP 403)"
    if status == 429:
        return f"Kit is rate limiting this key (HTTP 429){tries}; the next run tries again"
    return f"Kit answered HTTP {status} for {what}{tries}"


class _Reader:
    """The Kit reads of one run: a fresh client (so KIT_API_KEY and
    KIT_API_BASE are read now), at most _RATE_PER_SEC requests a second, with
    bounded retries and a check of every answer."""

    def __init__(self, key: str):
        self.key = key
        self.client = kit_api.KitClient(api_key=key, rate_limit_per_sec=_RATE_PER_SEC)
        self.requests = 0
        self.retries = 0
        self.per_state = False          # Kit refused status=all: read each state instead

    def get(self, what: str, call: Callable[[], dict]) -> dict:
        """One read, retried on 429, a Kit server error or no answer.
        Raises KitSyncError on any other failure, or when retries run out."""
        for attempt in range(_RETRIES + 1):
            self.requests += 1
            answer = call()
            status = answer.get("status") if isinstance(answer, dict) else None
            if isinstance(status, bool) or not isinstance(status, int):
                raise KitSyncError(f"Kit answered {what} in a shape the sync cannot read")
            if 200 <= status < 300:
                return answer
            if status == 0 or status == 429 or status >= 500:
                if attempt == _RETRIES:
                    raise KitSyncError(_failure(status, what, retried=True), status)
                self.retries += 1
                _sleep(_wait(answer.get("_retry_after"), attempt))
                continue
            said = [] if status in (401, 403) else _kit_said(answer, self.key)
            raise KitSyncError(_failure(status, what), status, said)
        raise KitSyncError(f"Kit failed for {what}")      # not reached

    def pages(self, what: str, items: str, fetch: Callable[[Optional[str]], dict]) -> list[list]:
        """Every page of one list, following pagination.end_cursor while
        has_next_page. Stops, failing the run, on a page in another shape or
        a cursor that is missing or comes back."""
        out: list[list] = []
        after: Optional[str] = None
        cursors: set[str] = set()
        for n in range(_MAX_PAGES):
            try:
                page = self.get(what, lambda cursor=after: fetch(cursor))
            except KitSyncError as e:
                e.page = n
                raise
            listed, pagination = page.get(items), page.get("pagination")
            if (not isinstance(listed, list) or not isinstance(pagination, dict)
                    or not isinstance(pagination.get("has_next_page"), bool)):
                raise KitSyncError(f"Kit answered {what} in a shape the sync cannot read")
            out.append(listed)
            if not pagination["has_next_page"]:
                return out
            cursor = pagination.get("end_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise KitSyncError(f"Kit's next-page cursor for {what} is missing or repeats, "
                                   "so the read stopped")
            cursors.add(cursor)
            after = cursor
        raise KitSyncError(f"{what} has more than {_MAX_PAGES} pages, so the read stopped")

    def all_tags(self) -> list[tuple[int, str]]:
        """(id, name) of every tag in the account, all pages."""
        found = []
        for page in self.pages("the tag list", "tags",
                               lambda after: self.client.list_tags_page(after=after)):
            for tag in page:
                if isinstance(tag, dict) and _as_id(tag.get("id")) and isinstance(tag.get("name"), str):
                    found.append((_as_id(tag["id"]), tag["name"]))
        return found

    def tag_subscribers(self, tag: KitTag, tagged_after: date, tagged_before: date) -> list:
        """Every subscriber who holds `tag` and was tagged in the padded days,
        whatever their state. When Kit refuses status=all on a first page, it
        reads each state instead (and so for the rest of the run): one person
        has one state, and a duplicate is merged by id later."""
        what = f"tag {_quote(tag.name)}"
        if not self.per_state:
            try:
                return [s for page in self.pages(
                    what, "subscribers",
                    lambda after: self.client.list_tag_subscribers(
                        tag.id, tagged_after=tagged_after, tagged_before=tagged_before, after=after,
                        status="all", per_page=kit_api.MAX_PER_PAGE)) for s in page]
            except KitSyncError as e:
                if e.status != 422 or e.page != 0:
                    raise
                self.per_state = True
                log.info("kit sync: Kit refused status=all; reading each state")
        rows = []
        for state in kit_api.SUBSCRIBER_STATES:
            rows.extend(s for page in self.pages(
                what, "subscribers",
                lambda after, state=state: self.client.list_tag_subscribers(
                    tag.id, tagged_after=tagged_after, tagged_before=tagged_before, after=after,
                    status=state, per_page=FALLBACK_PER_PAGE)) for s in page)
        return rows


def resolve(specs: list[TagSpec], kit_tags: list[tuple[int, str]]) -> tuple[list[KitTag], list[str]]:
    """Each configured name to Kit's tags: those named exactly so, else those
    whose name matches ignoring case and surrounding spaces. A name Kit does
    not have is a warning. A Kit tag reached by two names is read once, with
    the first name and its channel."""
    tags: list[KitTag] = []
    warnings: list[str] = []
    taken: dict[int, KitTag] = {}
    for spec in specs:
        exact = [i for i, n in kit_tags if n == spec.name]
        folded = spec.name.strip().casefold()
        found = list(dict.fromkeys(exact or [i for i, n in kit_tags if n.strip().casefold() == folded]))
        if not found:
            warnings.append(f"tag {_quote(spec.name)} is not in Kit")
            continue
        new = [i for i in found if i not in taken]
        if len(new) > 1:
            warnings.append(f"{len(new)} Kit tags are named {_quote(spec.name)}"
                            f"{'' if exact else ' (ignoring case)'}; all of them are read")
        clash = next((taken[i] for i in found if i in taken and taken[i].channel != spec.channel), None)
        if clash is not None:
            warnings.append(f"tags {_quote(clash.name)} and {_quote(spec.name)} name the same Kit tag; "
                            f"it is read once, with the channel of {_quote(clash.name)}")
        for tag_id in new:
            taken[tag_id] = KitTag(tag_id, spec.name, spec.channel)
            tags.append(taken[tag_id])
    return tags, warnings


# ─── one opt-in per subscriber ──────────────────────────────────────────────

def merge(seen: dict[int, dict], tags: list[KitTag]) -> list[LeadRow]:
    """One opt-in per subscriber from the tag times seen in the window:
    the earliest time; the channel of the earliest-tagged tag that has one
    (a tie goes to the tag listed first); the configured names seen as tags;
    the email lower-cased. raw keeps ids only."""
    by_id = {t.id: t for t in tags}
    order = {t.id: n for n, t in enumerate(tags)}
    rows = []
    for sub_id in sorted(seen):
        s = seen[sub_id]
        times: dict[int, datetime] = s["times"]
        ranked = sorted(times, key=lambda t: (times[t], order[t]))
        channel = next((by_id[t].channel for t in ranked if by_id[t].channel), None)
        rows.append(LeadRow(
            external_id=f"{FUNNEL}:sub:{sub_id}", kind="optin", occurred_at=times[ranked[0]],
            email=s["email"], funnel=FUNNEL, channel=channel,
            tags=tuple(sorted({by_id[t].name for t in ranked})),
            raw={"subscriber_id": sub_id, "tag_ids": sorted(times)}))
    return rows


def find_tags(reader: _Reader, specs: list[TagSpec], detail: dict) -> list[KitTag]:
    """The configured tags as Kit has them. A name Kit does not have is a
    warning in `detail` (the run's job_runs detail); none found fails the run."""
    tags, warnings = resolve(specs, reader.all_tags())
    if warnings:
        detail.setdefault("warnings", []).extend(warnings)
    detail["tags_read"] = [{"name": t.name, "id": t.id, "channel": t.channel} for t in tags]
    if not tags:
        names = ", ".join(_quote(s.name, 30) for s in specs[:5])
        raise KitSyncError(f"no tag in BOARD_TOODLE_KIT_TAGS is in Kit ({names}): check the tag names")
    return tags


def tag_set(tags: list[KitTag]) -> list[list]:
    """The tag set a run read, as its job_runs detail records it: each Kit tag
    id with the channel it sets, sorted by id ([[11, None], [12, "meta"]]),
    ids and channels only. A run whose tag set differs from the last complete
    run's reads from BOARD_BACKFILL_FROM again, so a tag or a channel added to
    BOARD_TOODLE_KIT_TAGS later reaches past days."""
    return [[t.id, t.channel] for t in sorted(tags, key=lambda t: t.id)]


def collect(reader: _Reader, tags: list[KitTag], since: datetime, until: datetime, detail: dict) -> list[LeadRow]:
    """Read every subscriber of `tags` tagged in [since, until) and merge them
    per subscriber. Returns the opt-ins. Fills `detail` as it goes, so a run
    that fails still records how far it got."""
    tagged_after = (since.astimezone(timezone.utc) - FILTER_PAD).date()
    tagged_before = (until.astimezone(timezone.utc) + FILTER_PAD).date()
    detail["filters"] = {"tagged_after": tagged_after.isoformat(), "tagged_before": tagged_before.isoformat()}
    seen: dict[int, dict] = {}
    listed = 0
    for tag in tags if since < until else []:
        for item in reader.tag_subscribers(tag, tagged_after, tagged_before):
            listed += 1
            if not isinstance(item, dict):
                raise KitSyncError(f"Kit listed a subscriber of tag {_quote(tag.name)} in a shape the "
                                   "sync cannot read, so nothing was written")
            sub_id, at = _as_id(item.get("id")), _as_time(item.get("tagged_at"))
            if sub_id is None or at is None:
                raise KitSyncError(f"Kit listed a subscriber of tag {_quote(tag.name)} without an id or a "
                                   "tag time, so nothing was written")
            if not since <= at < until:
                continue
            s = seen.setdefault(sub_id, {"email": None, "state": None, "times": {}})
            email = item.get("email_address")
            if s["email"] is None and isinstance(email, str) and email.strip():
                s["email"] = email.strip().lower()
            if s["state"] is None and isinstance(item.get("state"), str):
                s["state"] = item["state"][:20]
            if tag.id not in s["times"] or at < s["times"][tag.id]:
                s["times"][tag.id] = at
    detail.update(listed=listed, subscribers=len(seen),
                  states=dict(Counter(s["state"] or "unknown" for s in seen.values())),
                  query="each state (Kit refused status=all)" if reader.per_state else "status=all")
    return merge(seen, tags)


# ─── one run ────────────────────────────────────────────────────────────────

def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _first_whole_day(start: datetime) -> date:
    """measured_from: the New York day of the window's start, or the next day
    when the window starts after midnight (a day read only in part is not
    measured)."""
    local = start.astimezone(NY)
    return local.date() if local.time() == dtime(0) else local.date() + timedelta(days=1)


def _warning(warnings: list[str]) -> Optional[str]:
    """What an ok run must still tell the owner: the run's error and the
    source's last_error, so the board's note and the morning message show it."""
    text = "; ".join(warnings)
    if len(text) > 300:
        text = text[:297] + "..."
    return text or None


def run(trigger: str = "schedule", days: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """One sync run, claimed in job_runs. `days` widens the window to at least
    the last N days (it never narrows it, so no gap opens behind the
    watermark). Returns the run's fields (status ok, failed, busy or skipped);
    never raises."""
    started = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: dict = {"id": None, "job": JOB, "source_id": SOURCE_ID, "trigger_kind": trigger,
                 "status": None, "started_at": started.isoformat(), "finished_at": None,
                 "window_start": None, "window_end": None, "covered_until": None,
                 "rows_written": 0, "detail": {}, "error": None}
    reason = configured()
    if reason is not None:
        out.update(status="skipped", error=reason)
        return out
    key = api_key()
    specs, config_warnings = tag_specs()
    out["run_key"] = started.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    try:
        run_id = ledger.claim_run(JOB, out["run_key"], trigger, SOURCE_ID)
    except BoardDBError as e:
        log.warning("kit sync: cannot claim a run (%s)", e)
        out.update(status="failed", error=f"database: {e}")
        return out
    if run_id is None:
        out.update(status="busy", error="another Kit sync is running")
        return out
    out["id"] = run_id
    detail: dict = {"tags_configured": [s.name for s in specs]}
    if config_warnings:
        detail["warnings"] = list(config_warnings)
    out["detail"] = detail
    since = until = None
    try:
        src = ledger.source_row(SOURCE_ID)
        if src is None:
            raise BoardDBError("no 'kit' row in public.sources: apply migration 0002")
        if src.get("enabled") is False:
            ledger.finish_run(run_id, "skipped", detail=detail, error="the kit source is disabled")
            out.update(status="skipped", error="the kit source is disabled",
                       finished_at=datetime.now(timezone.utc).isoformat())
            return out
        watermark = ledger.parse_ts(src.get("synced_through"))
        first = watermark is None
        recorded = None if first else (ledger.last_ok_detail(JOB) or {}).get("tag_set")
        reader = _Reader(key)
        try:
            tags = find_tags(reader, specs, detail)
            detail["tag_set"] = tag_set(tags)
            # The first run, or the tag set changed since the last complete run
            # (no record: as before, from the watermark).
            from_backfill = first or (recorded is not None and recorded != detail["tag_set"])
            detail["from_backfill"] = from_backfill
            since = backfill_start() if from_backfill else watermark - OVERLAP
            if days:
                since = min(since, started - timedelta(days=days))
            until = started
            rows = collect(reader, tags, since, until, detail)
        except KitSyncError as e:
            if e.said:
                detail["kit_said"] = e.said
            raise
        finally:
            detail.update(requests=reader.requests, retries=reader.retries)
        result = (ledger.ingest_leads(SOURCE_ID, run_id, rows) if rows
                  else {"received": 0, "inserted": 0, "relabelled": 0})
        detail.update(result)
        error = _warning(detail.get("warnings") or [])
        covered = started - LAG
        ledger.finish_run(run_id, "ok", rows_written=result["inserted"], detail=detail, error=error,
                          window_start=since, window_end=until, covered_until=covered)
        ledger.mark_source_ok(SOURCE_ID, covered, _first_whole_day(since) if first else None, warning=error)
        out.update(status="ok", rows_written=result["inserted"], error=error,
                   window_start=_iso(since), window_end=_iso(until), covered_until=_iso(covered),
                   finished_at=datetime.now(timezone.utc).isoformat())
        log.info("kit sync ok: %s new of %s opt-ins (%s)", result["inserted"], result["received"], trigger)
    except Exception as e:  # noqa: BLE001 — a failed run is recorded, never left running
        if isinstance(e, (KitSyncError, BoardDBError)):
            message = str(e)[:300]
        else:
            message = f"unexpected {type(e).__name__}"
            log.exception("kit sync failed")
        log.warning("kit sync failed: %s", message)
        for step in (lambda: ledger.finish_run(run_id, "failed", detail=detail, error=message,
                                               window_start=since, window_end=until),
                     lambda: ledger.mark_source_error(SOURCE_ID, message)):
            try:
                step()
            except BoardDBError as db_error:
                log.warning("kit sync: could not record the failure (%s)", db_error)
        out.update(status="failed", error=message, window_start=_iso(since), window_end=_iso(until),
                   finished_at=datetime.now(timezone.utc).isoformat())
    return out
