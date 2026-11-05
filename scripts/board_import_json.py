#!/usr/bin/env python3
"""
scripts/board_import_json.py
─────────────────────────────────────────────────────────────────────────────
Bring what survives of the old JSON stores into the daily numbers board's
tables: manual money entries and /go clicks. Best effort, and safe to run
any number of times.

  data/stripe_payments.json  manual entries only (type manual_<source>, not
                             manual_stripe). Stripe's own payments in this
                             file are not imported: the Stripe sync reads
                             them from Stripe itself.
  data/revenue.json          entries whose source is not stripe and that
                             carry no metadata.stripe_id (those were Stripe
                             charges, which the Stripe sync has)
  data/clicks.json           every /go click, without its IP address: no IP
                             is read into any column or key

The old conversion log is not imported: attribution lives in the ledger now.

Each entry becomes a ledger row of the 'manual' source (a sale, or an
adjustment when negative; USD; fee unknown), keyed by a SHA-256 of the whole
JSON record, so a second run finds every row already there and changes no
money. Each click is keyed by a SHA-256 of its partner, time, referrer and
destination (never the IP), so two records that differ only in IP are one
click. A click keeps the referring host only (never the path) and no UTM tags:
the old log never recorded the visitor's own. The run is recorded in job_runs
as 'json_import'.

Every deploy wipes data/ on Railway: copy these files out of the running
service BEFORE the deploy that ships this script, then run it from your own
machine, before or after that deploy.

Usage:
  python scripts/board_import_json.py [--dir FOLDER] [--naive-tz ZONE] [--dry-run] [--only manual|clicks]

  --dir       the folder that holds the copied files (default: data/ here)
  --naive-tz  the time zone of times written without one (default UTC: the
              Railway container's clock). Files copied from a local run may
              need your own zone, such as America/New_York.
  --dry-run   read the files and say what would be imported; write nothing
  --only      import only the manual entries, or only the clicks

Needs SUPABASE_URL and SUPABASE_SERVICE_KEY (the service-role key; in .env
or the shell) and migration 0002 applied. Exit codes: 0 done, 1 nothing
imported because the database is not connected (or another import is
running), 2 bad input (a file that is not JSON, an unknown time zone).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:          # the shell's own variables then
    pass

from core.board import ledger                      # noqa: E402 — after the path is set
from core.board.ledger import BoardDBError, LedgerRow   # noqa: E402
from core.click_tracker import PARTNER_RE, referrer_host   # noqa: E402 — the live /go rules

PAYMENTS, REVENUE, CLICKS = "stripe_payments.json", "revenue.json", "clicks.json"
JOB = "json_import"
MAX_CENTS = 100_000_000                 # $1,000,000.00 a single entry, as the live route
SOURCE_LONGEST, NOTE_LONGEST = 64, 500
SKIP_WORDS = {                           # why a record was skipped, in the summary's words
    "stripe_payments": "Stripe's own payments (the Stripe sync reads them from Stripe)",
    "stripe_entries": "marked as Stripe money (the Stripe sync reads it from Stripe)",
    "zero": "an amount of $0",
    "bad_amount": "an amount that is not a number of dollars",
    "too_large": "an amount above $1,000,000",
    "bad_time": "a time that is missing or unreadable",
    "future": "dated more than a day ahead",
    "not_a_record": "not a record",
    "same_entry_twice": "listed twice",
    "bad_partner": "a partner key that is not a-z, 0-9, _ or -",
    "bad_destination": "a destination that is missing or longer than 2,048 characters",
    "same_click_twice": "listed twice (some differ only in IP address)",
}


class BadInput(Exception):
    """A file that cannot be imported as it is: the message names it."""


# ─── reading ────────────────────────────────────────────────────────────────

def _read(folder: Path, name: str):
    """The JSON in folder/name, or None when the file is not there."""
    path = folder / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise BadInput(f"{name} could not be read as JSON ({type(e).__name__}).") from None


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _when(value, zone: ZoneInfo, now: datetime) -> tuple[Optional[datetime], Optional[str]]:
    """(the instant, None) or (None, why it is skipped). A time without a zone
    is read in `zone`."""
    if not isinstance(value, str) or not value.strip():
        return None, "bad_time"
    try:
        at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None, "bad_time"
    if at.tzinfo is None:
        at = at.replace(tzinfo=zone)
    if at > now + timedelta(days=1):
        return None, "future"
    return at, None


def _cents(value, counts: Counter) -> tuple[Optional[int], Optional[str]]:
    """(US cents, None) or (None, why it is skipped). A float is read as
    written (repr); more than 2 decimal places is rounded half up to the cent
    and counted."""
    if isinstance(value, bool):
        return None, "bad_amount"
    try:
        if isinstance(value, float):
            if not math.isfinite(value):
                return None, "bad_amount"
            amount = Decimal(repr(value))
        elif isinstance(value, int):
            amount = Decimal(value)
        elif isinstance(value, str):
            amount = Decimal(value.strip())
        else:
            return None, "bad_amount"
    except InvalidOperation:
        return None, "bad_amount"
    if not amount.is_finite():
        return None, "bad_amount"
    if abs(amount) > Decimal(MAX_CENTS) / 100:
        return None, "too_large"
    exact = amount * 100
    cents = exact.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if cents == 0:
        return None, "zero"
    if cents != exact:
        counts["rounded"] += 1
    return int(cents), None


def _text(value, longest: int) -> str:
    return (value if isinstance(value, str) else "" if value is None else str(value)).replace("\x00", "").strip()[:longest]


def _plain_values(metadata) -> dict:
    """The plain values of a record's metadata, never one under an email key."""
    out: dict = {}
    if not isinstance(metadata, dict):
        return out
    for k, v in list(metadata.items())[:20]:
        if not isinstance(k, str) or "email" in k.lower():
            continue
        if isinstance(v, float) and not math.isfinite(v):
            continue
        if v is None or isinstance(v, (bool, int, float)):
            out[k[:64]] = v
        elif isinstance(v, str):
            out[k[:64]] = _text(v, NOTE_LONGEST)
    return out


def _entry(record: dict, prefix: str, amount, ts, source: str, words: str, raw: dict,
           zone: ZoneInfo, now: datetime, counts: Counter) -> Optional[LedgerRow]:
    cents, why = _cents(amount, counts)
    at, why_time = _when(ts, zone, now) if why is None else (None, None)
    why = why or why_time
    if why is not None:
        counts["skipped:" + why] += 1
        return None
    return ledger.manual_row(prefix + _digest(record)[:40], cents, at,
                             product=f"{source}: {words}" if words else source, raw=raw)


def manual_from_payments(records, zone: ZoneInfo, now: datetime, counts: Counter) -> list[LedgerRow]:
    """The manual entries of data/stripe_payments.json (the old payment log)."""
    if not isinstance(records, list):
        raise BadInput(f"{PAYMENTS} is not a list of records.")
    rows = []
    for record in records:
        counts["read"] += 1
        if not isinstance(record, dict):
            counts["skipped:not_a_record"] += 1
            continue
        kind = record.get("type")
        if not isinstance(kind, str) or not kind.startswith("manual_"):
            counts["skipped:stripe_payments"] += 1        # what the webhook logged: Stripe's own money
            continue
        source = _text(kind[len("manual_"):], SOURCE_LONGEST) or "manual"
        if source.lower() == "stripe":
            counts["skipped:stripe_entries"] += 1
            continue
        note = _text(record.get("product"), NOTE_LONGEST)    # the old route stored the note there
        raw = {"imported_from": PAYMENTS, "source": source, "note": note,
               "legacy_event_id": _text(record.get("event_id"), 255)}
        row = _entry(record, "import:stripe_payments:", record.get("amount"), record.get("ts"), source, note,
                     raw, zone, now, counts)
        if row is not None:
            rows.append(row)
    return rows


def manual_from_revenue(data, zone: ZoneInfo, now: datetime, counts: Counter) -> list[LedgerRow]:
    """The entries of data/revenue.json (the old RevenueEngine store) that
    were not Stripe charges."""
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise BadInput(f"{REVENUE} has no list of records.")
    rows = []
    for record in records:
        counts["read"] += 1
        if not isinstance(record, dict) or not isinstance(record.get("source"), str):
            counts["skipped:not_a_record"] += 1
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source = _text(record["source"], SOURCE_LONGEST) or "manual"
        if source.lower() == "stripe" or metadata.get("stripe_id"):
            counts["skipped:stripe_entries"] += 1
            continue
        label = _text(record.get("label"), NOTE_LONGEST)
        raw = {"imported_from": REVENUE, "source": source, "label": label}
        extra = _plain_values(metadata)
        if extra:
            raw["metadata"] = extra
        row = _entry(record, "import:revenue:", record.get("amount"), record.get("ts"), source, label,
                     raw, zone, now, counts)
        if row is not None:
            rows.append(row)
    return rows


def clicks_from_file(records, zone: ZoneInfo, now: datetime, counts: Counter) -> list[dict]:
    """The clicks of data/clicks.json as rows of public.clicks, checked as the
    live /go route checks a click: the key lower-cased and 1 to 64 of a-z,
    0-9, _ and -; the referring host only; a destination of 1 to 2,048
    characters; no UTM tags (utm {}). The record's IP address is never read."""
    if not isinstance(records, list):
        raise BadInput(f"{CLICKS} is not a list of clicks.")
    rows, seen = [], set()
    for record in records:
        counts["read"] += 1
        if not isinstance(record, dict):
            counts["skipped:not_a_record"] += 1
            continue
        partner = record.get("partner").strip().lower() if isinstance(record.get("partner"), str) else ""
        if not PARTNER_RE.fullmatch(partner):
            counts["skipped:bad_partner"] += 1
            continue
        at, why = _when(record.get("ts"), zone, now)
        if why is not None:
            counts["skipped:" + why] += 1
            continue
        destination = record.get("dest")
        if not isinstance(destination, str) or not 1 <= len(destination) <= 2048:
            counts["skipped:bad_destination"] += 1
            continue
        key = "sha256:" + _digest({"partner": record.get("partner"), "ts": record.get("ts"),
                                   "referrer": record.get("referrer"), "dest": destination})
        if key in seen:
            counts["skipped:same_click_twice"] += 1
            continue
        seen.add(key)
        rows.append({"partner": partner, "clicked_at": at.astimezone(timezone.utc).isoformat(),
                     "referrer_host": referrer_host(record.get("referrer")), "destination": destination,
                     "utm": {}, "import_key": key})
    return rows


def _unique(rows: list[LedgerRow], counts: Counter) -> list[LedgerRow]:
    out, seen = [], set()
    for r in rows:
        if r.external_id in seen:
            counts["skipped:same_entry_twice"] += 1
            continue
        seen.add(r.external_id)
        out.append(r)
    return out


# ─── the run ────────────────────────────────────────────────────────────────

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import manual money entries and /go clicks from the old JSON "
                                            "files into the daily numbers board's tables.")
    p.add_argument("--dir", default=str(ROOT / "data"), help="the folder with the copied files (default: data/)")
    p.add_argument("--naive-tz", default="UTC", help="the zone of times written without one (default: UTC)")
    p.add_argument("--dry-run", action="store_true", help="say what would be imported; write nothing")
    p.add_argument("--only", choices=("manual", "clicks"), help="import only one kind")
    return p


def _skips(counts: Counter) -> dict:
    return {k.split(":", 1)[1]: n for k, n in sorted(counts.items()) if k.startswith("skipped:")}


def _say_skips(what: str, counts: Counter) -> list[str]:
    """'  Manual entries skipped, an amount of $0: 1', one line per reason."""
    lines = [f"  {what} skipped, {SKIP_WORDS.get(reason, reason)}: {n:,}" for reason, n in _skips(counts).items()]
    if counts["rounded"]:
        lines.append(f"  {what} rounded to the cent (more than 2 decimal places): {counts['rounded']:,}")
    return lines


def main(argv=None, *, now: Optional[datetime] = None) -> int:
    args = _parser().parse_args(argv)
    now = now or datetime.now(timezone.utc)
    try:
        zone = ZoneInfo(args.naive_tz)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"Nothing was imported: --naive-tz {args.naive_tz!r} is not a time zone. "
              "Use a name such as UTC or America/New_York.")
        return 2
    folder = Path(args.dir).expanduser()
    if not folder.is_dir():
        print(f"Nothing was imported: {folder} is not a folder.")
        return 2
    print(f"Reading the files in {folder}.")

    manual_counts, click_counts = Counter(), Counter()
    rows: list[LedgerRow] = []
    clicks: list[dict] = []
    found: dict[str, str] = {}
    try:
        names = ((PAYMENTS, REVENUE) if args.only != "clicks" else ()) + ((CLICKS,) if args.only != "manual" else ())
        for name in names:
            data = _read(folder, name)
            found[name] = "missing" if data is None else "read"
            if data is None:
                continue
            if name == PAYMENTS:
                rows += manual_from_payments(data, zone, now, manual_counts)
            elif name == REVENUE:
                rows += manual_from_revenue(data, zone, now, manual_counts)
            else:
                clicks = clicks_from_file(data, zone, now, click_counts)
    except BadInput as e:
        print(f"Nothing was imported: {e}")
        return 2
    rows = _unique(rows, manual_counts)
    for name, state in found.items():
        if state == "missing":
            print(f"{name} is not in {folder}: nothing to import from it.")

    if args.dry_run:
        print(f"Dry run: nothing was written. {len(rows):,} manual entries and {len(clicks):,} clicks would be "
              "imported (IP addresses dropped).")
        for line in _say_skips("Manual entries", manual_counts) + _say_skips("Clicks", click_counts):
            print(line)
        return 0

    if ledger.db_settings() is None:
        print("Nothing was imported: set SUPABASE_URL and SUPABASE_SERVICE_KEY (the service-role key) first.")
        return 1
    run_key = f"{JOB}:{now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}"
    try:
        run_id = ledger.claim_run(JOB, run_key, "script", ledger.MANUAL_SOURCE)
    except BoardDBError as e:
        print(f"Nothing was imported: the database is not connected, or migration 0002 is not applied ({e}).")
        return 1
    if run_id is None:
        print("Nothing was imported: another import is running. Try again when it has finished. "
              "An import that was cut off is released after 30 minutes.")
        return 1

    written = {"received": 0, "inserted": 0, "relabelled": 0, "money_mismatches": 0}
    new_clicks = 0
    detail = {"files": found, "naive_tz": args.naive_tz,
              "manual": {"read": manual_counts["read"], "to_import": len(rows), "rounded": manual_counts["rounded"],
                         "skipped": _skips(manual_counts)},
              "clicks": {"read": click_counts["read"], "to_import": len(clicks), "skipped": _skips(click_counts)}}
    try:
        if rows:
            written = ledger.ingest_ledger(ledger.MANUAL_SOURCE, run_id, rows)
        if clicks:
            new_clicks = ledger.import_clicks(clicks)
    except BoardDBError as e:
        try:
            ledger.finish_run(run_id, "failed", detail=detail, error=f"the import stopped: {e}")
        except BoardDBError:
            pass
        print(f"The import stopped: the database refused a write ({e}). What was written is kept; "
              "run the import again to finish it.")
        return 1
    detail["manual"].update(new=written["inserted"], already_there=written["relabelled"],
                            money_mismatches=written["money_mismatches"])
    detail["clicks"].update(new=new_clicks, already_there=len(clicks) - new_clicks)
    try:
        ledger.finish_run(run_id, "ok", rows_written=written["inserted"] + new_clicks, detail=detail)
    except BoardDBError as e:
        print(f"The rows are written, but the run could not be marked done ({e}).")

    print(f"Imported {len(rows):,} manual entries ({written['inserted']:,} new, {written['relabelled']:,} already "
          f"there) and {len(clicks):,} clicks ({new_clicks:,} new, {len(clicks) - new_clicks:,} already there). "
          "IP addresses were dropped.")
    if written["money_mismatches"]:
        print(f"  {written['money_mismatches']:,} entries were already there with another time or amount. "
              "They were kept as they were: money is written once.")
    for line in _say_skips("Manual entries", manual_counts) + _say_skips("Clicks", click_counts):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
