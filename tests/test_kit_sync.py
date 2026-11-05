"""The Kit connector (core/board/connectors/kit_sync.py) and the Kit client's
page reads (core/kit.py: list_tags_page, list_tag_subscribers). Toodle opt-ins
come from the tags' subscriber lists, one per subscriber. No network: Kit is
faked here, behind core.kit's `requests`, and Supabase in tests/board_fakes.py."""
import base64
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from core import kit as core_kit
from core.board import ledger
from core.board.connectors import kit_sync
from tests import board_fakes as bf

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 in New York
KIT_KEY = "kit_FAKEtestKey0a1b2c3d4e5f6a7b8c9d"              # fake
BASE = "https://api.kit.com/v4"
TAGS = "toodle:,meta_ad:meta,blog:organic"
STATES = ("active", "inactive", "bounced", "complained", "cancelled")
RATE_PER_SEC = kit_sync._RATE_PER_SEC        # the sync's own pace, read before the kit fixture raises it


# ─── a fake Kit v4 API ──────────────────────────────────────────────────────

def _response(status: int, body=None, headers=None, text=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = text.encode() if text is not None else b"" if body is None else json.dumps(body).encode()
    r.headers = CaseInsensitiveDict(headers or {})
    r.encoding = "utf-8"
    return r


def _cursor(offset: int) -> str:
    """Kit's cursors are base64 and may end in '=', which must be URL-encoded."""
    return base64.b64encode(json.dumps({"offset": offset}).encode()).decode()


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class FakeKit:
    """GET /v4/tags and GET /v4/tags/{id}/subscribers over cursor pages, as
    core.kit's requests.request. tagged_after and tagged_before get the
    narrowest reading Kit's docs allow: "after" leaves out the whole day in
    the westernmost zone (UTC-12), "before" the whole day in the easternmost
    (UTC+14), so only a padded filter keeps every tag time of the window."""

    def __init__(self, key: str = KIT_KEY):
        self.key = key
        self.tags: list[dict] = []
        self.taggings: dict[int, list[dict]] = {}     # tag id -> its subscribers, each with tagged_at
        self.calls: list[dict] = []
        self.fail_next: list = []                     # answers (or exceptions) for the next calls, any path
        self.fail_on: dict[str, list] = {}            # path -> answers for its next calls
        self.page_size = None                         # a cap on per_page (None: as asked)
        self.max_subscriber_page = 1000
        self.refuse_all = False                       # 422 for status=all
        self.sleeps: list[float] = []                 # kit_sync's waits before a retry

    def add_tag(self, tag_id: int, name: str) -> None:
        self.tags.append({"id": tag_id, "name": name, "created_at": "2026-01-02T10:00:00Z"})

    def tag(self, tag_id: int, sub_id: int, at: str, email=None, state="active") -> None:
        self.taggings.setdefault(tag_id, []).append({
            "id": sub_id, "first_name": "Ada", "email_address": email or f"sub{sub_id}@example.com",
            "state": state, "created_at": "2025-06-01T09:00:00Z", "tagged_at": at,
            "fields": {"phone": "555-0100", "company": "Private Co"}})

    def calls_to(self, path: str) -> list[dict]:
        return [c for c in self.calls if c["path"] == path]

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        prepared = requests.Request(method, url, params=params).prepare()
        split = urlsplit(prepared.url)
        query = {k: v[0] for k, v in parse_qs(split.query, keep_blank_values=True).items()}
        headers = dict(headers or {})
        self.calls.append({"method": method, "path": split.path, "params": dict(params or {}),
                           "query": query, "url": prepared.url, "headers": headers})
        if not url.startswith(BASE + "/"):
            return _response(404, {"errors": ["Not Found"]})
        if headers.get("X-Kit-Api-Key") != self.key:      # Kit's words may repeat the key it was sent
            return _response(401, {"errors": [f"The API key {headers.get('X-Kit-Api-Key')} is not valid"]})
        queued = self.fail_on.get(split.path)
        if queued:
            return self._answer(queued.pop(0))
        if self.fail_next:
            return self._answer(self.fail_next.pop(0))
        if method != "GET":
            return _response(405, {"errors": ["Method not allowed"]})
        if split.path == "/v4/tags":
            return self._page(query, self.tags, "tags", 1000)
        m = re.fullmatch(r"/v4/tags/([0-9]+)/subscribers", split.path)
        if m is None:
            return _response(404, {"errors": ["Not Found"]})
        tag_id = int(m.group(1))
        if not any(t["id"] == tag_id for t in self.tags):
            return _response(404, {"errors": ["Not Found"]})
        status = query.get("status", "active")
        if status not in ("all", *STATES) or (status == "all" and self.refuse_all):
            return _response(422, {"errors": ["Status is not included in the list"]})
        rows = [r for r in self.taggings.get(tag_id, []) if status == "all" or r["state"] == status]
        for name in ("tagged_after", "tagged_before"):
            if name in query and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", query[name]):
                return _response(422, {"errors": [f"{name} is not a date"]})
        if "tagged_after" in query:
            lo = datetime.combine(date.fromisoformat(query["tagged_after"]) + timedelta(days=1), time(0),
                                  timezone(timedelta(hours=-12)))
            rows = [r for r in rows if "tagged_at" not in r or _when(r["tagged_at"]) >= lo]
        if "tagged_before" in query:
            hi = datetime.combine(date.fromisoformat(query["tagged_before"]), time(0), timezone(timedelta(hours=14)))
            rows = [r for r in rows if "tagged_at" not in r or _when(r["tagged_at"]) < hi]
        return self._page(query, rows, "subscribers", self.max_subscriber_page)

    @staticmethod
    def _answer(item):
        if isinstance(item, Exception):
            raise item
        status, body, headers = item
        return _response(status, body, headers)

    def _page(self, query: dict, rows: list, key: str, most: int):
        per_page = int(query.get("per_page", 500))
        if not 1 <= per_page <= most:
            return _response(422, {"errors": [f"Per page must be less than or equal to {most}"]})
        size = min(per_page, self.page_size or per_page)
        start = json.loads(base64.b64decode(query["after"]))["offset"] if "after" in query else 0
        chunk = rows[start:start + size]
        pagination = {"has_previous_page": start > 0, "has_next_page": start + size < len(rows),
                      "start_cursor": _cursor(start) if chunk else None,
                      "end_cursor": _cursor(start + len(chunk)) if chunk else None, "per_page": per_page}
        if query.get("include_total_count") == "true":
            pagination["total_count"] = len(rows)
        return _response(200, {key: chunk, "pagination": pagination})


@pytest.fixture
def db(monkeypatch):
    return bf.install_board(monkeypatch)


@pytest.fixture
def kit(monkeypatch):
    """A fresh FakeKit behind core.kit, the Kit settings for these tests, and
    no real waiting."""
    fake = FakeKit()
    monkeypatch.setenv("KIT_API_KEY", KIT_KEY)
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", TAGS)
    for name in ("KIT_API_BASE", "KIT_DRY_RUN", "BOARD_BACKFILL_FROM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(core_kit, "requests",
                        SimpleNamespace(request=fake.request, RequestException=requests.RequestException))
    monkeypatch.setattr(kit_sync, "_sleep", fake.sleeps.append)
    monkeypatch.setattr(kit_sync, "_RATE_PER_SEC", 1e6)
    for tag_id, name in ((11, "toodle"), (12, "meta_ad"), (13, "blog"), (14, "newsletter")):
        fake.add_tag(tag_id, name)
    return fake


def _rows(db):
    return db.lead_rows("kit")


# ─── configuration ──────────────────────────────────────────────────────────

def test_tags_split_on_the_last_colon_and_a_bad_channel_is_ignored_with_a_warning(monkeypatch):
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", " toodle: , meta_ad : META ,Lead: Magnet:,blog:organic,,"
                                                "odd:Meta Ads!,:meta,toodle:organic,plain")
    specs, warnings = kit_sync.tag_specs()
    assert specs == [kit_sync.TagSpec("toodle"), kit_sync.TagSpec("meta_ad", "meta"),
                     kit_sync.TagSpec("Lead: Magnet"), kit_sync.TagSpec("blog", "organic"),
                     kit_sync.TagSpec("odd"), kit_sync.TagSpec("plain")]
    assert warnings == ['tag "odd": the channel "Meta Ads!" is not letters, digits or _, so it was ignored',
                        '":meta" names no tag, so it was ignored',
                        'tag "toodle" is listed twice; the first is used']


@pytest.mark.parametrize("env, reason", [
    ({"KIT_API_KEY": None}, "Kit key not set: KIT_API_KEY"),
    ({"KIT_API_KEY": "   "}, "Kit key not set: KIT_API_KEY"),
    ({"KIT_API_KEY": "kit_FAKEtest\nKey"}, "KIT_API_KEY holds spaces or other characters a key cannot have"),
    ({"BOARD_TOODLE_KIT_TAGS": None}, "Toodle tags not set: BOARD_TOODLE_KIT_TAGS"),
    ({"BOARD_TOODLE_KIT_TAGS": " , :meta"}, "BOARD_TOODLE_KIT_TAGS names no tag"),
])
def test_without_a_key_or_tags_the_sync_is_skipped_and_kit_reads_not_connected(db, kit, monkeypatch, env, reason):
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert kit_sync.configured() == reason
    out = kit_sync.run(now=NOW)
    assert (out["status"], out["error"], out["id"]) == ("skipped", reason, None)
    assert kit.calls == [] and db.calls == []                  # no claim, no read, no watermark
    assert "FAKEtest" not in json.dumps(out)
    states = {s["id"]: s["state"] for s in ledger.board_day(date(2026, 11, 1))["sources"]}
    assert states["kit"] == "not_connected"                    # never a 0


def test_configured_when_the_key_and_a_tag_are_set(kit):
    assert kit_sync.configured() is None
    assert kit_sync.api_key() == KIT_KEY


# ─── the client's page reads (core/kit.py) ──────────────────────────────────

def test_list_tag_subscribers_asks_kit_for_one_page_as_documented(kit):
    client = core_kit.KitClient()
    page = client.list_tag_subscribers(11, tagged_after=date(2026, 10, 30), tagged_before="2026-11-04",
                                       after=_cursor(2), include_total_count=True)
    call = kit.calls[-1]
    assert (call["method"], call["path"]) == ("GET", "/v4/tags/11/subscribers")
    assert call["query"] == {"status": "all", "per_page": "1000", "tagged_after": "2026-10-30",
                             "tagged_before": "2026-11-04", "after": _cursor(2), "include_total_count": "true"}
    assert _cursor(2).endswith("=") and "after=" + _cursor(2).replace("=", "%3D") in call["url"]
    assert call["headers"] == {"X-Kit-Api-Key": KIT_KEY, "Accept": "application/json"}
    assert page["status"] == 200 and page["subscribers"] == [] and page["pagination"]["total_count"] == 0
    for bad in ({"status": "everyone"}, {"per_page": 1001}, {"per_page": True}, {"tagged_after": "1 Nov"}):
        with pytest.raises(ValueError):
            client.list_tag_subscribers(11, **bad)
    with pytest.raises(ValueError):
        client.list_tag_subscribers(True)
    assert len(kit.calls) == 1                                 # a bad argument never reaches Kit


def test_reads_reach_kit_in_dry_run_and_writes_do_not(kit, monkeypatch):
    monkeypatch.setenv("KIT_DRY_RUN", "true")
    client = core_kit.KitClient()
    assert client.dry_run is True
    assert client.list_tag_subscribers(11)["status"] == 200
    assert client.list_tags_page()["status"] == 200
    assert client.create_tag("x")["_dry_run"] is True
    assert [c["method"] for c in kit.calls] == ["GET", "GET"]


def test_list_tags_keeps_its_contract_and_list_tags_page_tells_a_failure_from_no_tags(kit):
    client = core_kit.KitClient()
    assert [t["name"] for t in client.list_tags()] == ["toodle", "meta_ad", "blog", "newsletter"]
    assert kit.calls[-1]["query"] == {}                        # one page at Kit's default size, as before
    page = client.list_tags_page()
    assert page["status"] == 200 and kit.calls[-1]["query"] == {"per_page": "1000"}
    assert page["pagination"]["has_next_page"] is False
    kit.fail_next = [(500, {"errors": ["Something went wrong"]}, {})]
    assert client.list_tags() == []                            # unchanged: a failure still reads as no tags
    kit.fail_next = [(500, {"errors": ["Something went wrong"]}, {"Retry-After": "3"})]
    failed = client.list_tags_page()
    assert failed["status"] == 500 and failed["_retry_after"] == "3"


def test_a_network_error_is_returned_and_logged_by_its_type_only(kit, caplog):
    caplog.set_level(logging.DEBUG)
    kit.fail_next = [requests.exceptions.InvalidHeader(f"Invalid return character in header value: {KIT_KEY!r}")]
    assert core_kit.KitClient().list_tags_page() == {"error": "request failed (InvalidHeader)", "status": 0}
    assert KIT_KEY not in caplog.text


def test_an_answer_that_is_not_a_json_object_is_kept_not_indexed(kit):
    kit.fail_next = [(200, [1, 2], {}), (502, None, {})]
    assert core_kit.KitClient().list_tags_page() == {"raw": [1, 2], "status": 200}
    assert core_kit.KitClient().list_tags() == []


# ─── a run: claim, read, merge, write, move the watermark ───────────────────

def test_the_first_run_backfills_from_board_backfill_from_and_sets_measured_from(db, kit):
    kit.tag(11, 101, "2026-11-01T16:00:00Z", "Ada@Example.com")
    kit.tag(11, 102, "2025-12-31T20:00:00Z")       # 15:00 on 31 Dec in New York: before the backfill
    kit.tag(11, 103, "2026-01-01T05:00:00Z")       # midnight on 1 Jan in New York: the first moment read
    kit.tag(11, 104, "2026-11-02T12:30:00Z")       # after the run started: the next run reads it
    kit.tag(11, 105, "2026-11-02T12:00:00Z")       # the run's start itself: also the next run's
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and out["error"] is None, out
    assert set(_rows(db)) == {"toodle:sub:101", "toodle:sub:103"}
    (call,) = kit.calls_to("/v4/tags/11/subscribers")
    # the window is midnight 1 Jan in New York (05:00Z) to the run's start, asked for with 2 days to spare
    assert call["query"] == {"status": "all", "per_page": "1000", "tagged_after": "2025-12-30",
                             "tagged_before": "2026-11-04"}
    assert out["window_start"] == "2026-01-01T05:00:00+00:00" and out["window_end"] == NOW.isoformat()
    assert out["detail"]["listed"] == 5 and out["detail"]["subscribers"] == 2
    src = db.sources["kit"]
    assert src["measured_from"] == date(2026, 1, 1)
    assert src["synced_through"] == NOW - timedelta(minutes=10)            # the run's start minus 10 min
    assert src["last_error"] is None and src["last_ok_at"] is not None
    (run,) = db.runs("kit_sync")
    assert run["status"] == "ok" and run["source_id"] == "kit" and run["rows_written"] == 2
    assert run["covered_until"] == NOW - timedelta(minutes=10)
    assert all(r["job_run_id"] == run["id"] for r in _rows(db).values())
    assert {c["path"] for c in kit.calls} == {"/v4/tags", "/v4/tags/11/subscribers",
                                              "/v4/tags/12/subscribers", "/v4/tags/13/subscribers"}


def test_tags_are_found_by_exact_name_then_ignoring_case_and_a_missing_one_is_a_warning(db, kit):
    kit.tags = []
    kit.add_tag(21, "Toodle")
    kit.add_tag(22, "toodle")                     # the exact name wins over "Toodle"
    kit.add_tag(23, " META_AD")                   # matches meta_ad, ignoring case and spaces
    kit.tag(23, 5, "2026-11-02T11:00:00Z")
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok"
    assert out["detail"]["tags_read"] == [{"name": "toodle", "id": 22, "channel": None},
                                          {"name": "meta_ad", "id": 23, "channel": "meta"}]
    assert out["error"] == 'tag "blog" is not in Kit' and out["detail"]["warnings"] == [out["error"]]
    src = db.sources["kit"]
    assert src["last_error"] == out["error"] and src["last_error_at"] == src["last_ok_at"]   # a warning
    assert {c["path"] for c in kit.calls if c["path"].endswith("/subscribers")} == \
        {"/v4/tags/22/subscribers", "/v4/tags/23/subscribers"}
    assert _rows(db)["toodle:sub:5"]["channel"] == "meta"


def test_resolve_reads_every_case_match_and_one_kit_tag_once():
    specs = [kit_sync.TagSpec("Toodle", "meta"), kit_sync.TagSpec("TOODLE", "organic")]
    tags, warnings = kit_sync.resolve(specs, [(1, "toodle"), (2, "TOODLE "), (3, "other")])
    assert tags == [kit_sync.KitTag(1, "Toodle", "meta"), kit_sync.KitTag(2, "Toodle", "meta")]
    assert warnings == ['2 Kit tags are named "Toodle" (ignoring case); all of them are read',
                        'tags "Toodle" and "TOODLE" name the same Kit tag; it is read once, with the channel '
                        'of "Toodle"']
    same = kit_sync.resolve([kit_sync.TagSpec("meta", "meta"), kit_sync.TagSpec("Meta", "meta")], [(5, "meta")])
    assert same == ([kit_sync.KitTag(5, "meta", "meta")], [])        # the same channel: nothing to say


def test_the_run_fails_when_no_configured_tag_is_in_kit(db, kit, monkeypatch):
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "nope:meta,missing")
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == 'no tag in BOARD_TOODLE_KIT_TAGS is in Kit ("nope", "missing"): check the tag names'
    assert out["detail"]["warnings"] == ['tag "nope" is not in Kit', 'tag "missing" is not in Kit']
    assert _rows(db) == {} and db.sources["kit"]["synced_through"] is None
    assert db.sources["kit"]["measured_from"] is None and db.sources["kit"]["last_error"] == out["error"]


def test_every_page_is_read_and_cursors_are_url_encoded(db, kit):
    kit.page_size = 2
    for n in range(5):
        kit.add_tag(100 + n, f"filler {n}")                    # 9 tags: 5 pages
        kit.tag(11, 200 + n, f"2026-11-01T1{n}:00:00Z")        # 5 subscribers: 3 pages
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["subscribers"] == 5 and len(_rows(db)) == 5
    assert len(kit.calls_to("/v4/tags")) == 5
    pages = kit.calls_to("/v4/tags/11/subscribers")
    assert len(pages) == 3 and "after" not in pages[0]["query"]
    assert [p["query"]["after"] for p in pages[1:]] == [_cursor(2), _cursor(4)]
    assert all("%3D" in p["url"] and p["query"]["tagged_after"] == "2025-12-30" for p in pages[1:])


def test_a_cursor_that_comes_back_stops_the_read_and_fails_the_run(db, kit, monkeypatch):
    kit.tag(11, 1, "2026-11-01T12:00:00Z")
    looping = {"subscribers": [], "pagination": {"has_next_page": True, "end_cursor": _cursor(0)}}
    kit.fail_on["/v4/tags/11/subscribers"] = [(200, looping, {}), (200, looping, {})]
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == 'Kit\'s next-page cursor for tag "toodle" is missing or repeats, so the read stopped'
    assert _rows(db) == {} and db.sources["kit"]["synced_through"] is None


def test_two_tags_for_one_subscriber_make_one_opt_in_from_the_earliest_tag(db, kit):
    kit.tag(13, 7, "2026-11-01T13:05:00Z", "Bo@Example.COM", state="cancelled")   # blog (organic)
    kit.tag(11, 7, "2026-11-01T13:00:00Z", "Bo@Example.COM", state="cancelled")   # toodle: the first tag
    kit.tag(12, 7, "2026-11-01T13:02:00Z", "Bo@Example.COM", state="cancelled")   # meta_ad: the first with a channel
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["received"] == 1
    row = _rows(db)["toodle:sub:7"]
    assert row["occurred_at"] == datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
    assert (row["kind"], row["funnel"], row["channel"]) == ("optin", "toodle", "meta")
    assert row["tags"] == ["blog", "meta_ad", "toodle"] and row["email"] == "bo@example.com"
    assert row["raw"] == {"subscriber_id": 7, "tag_ids": [11, 12, 13]}       # ids only: no names, no fields
    (sent,) = db.rpc_calls("board_ingest_leads")[0]["p_rows"]
    assert sent["email"] == "bo@example.com" and sent["external_id"] == "toodle:sub:7"   # lower-cased before the SQL
    # someone who unsubscribed since still opted in that day
    assert out["detail"]["states"] == {"cancelled": 1}
    assert ledger.board_day(date(2026, 11, 1))["optins"] == {"total": 1, "by_channel": {"meta": 1}}


def test_a_tie_goes_to_the_tag_listed_first(db, kit, monkeypatch):
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "blog:organic,meta_ad:meta")
    kit.tag(12, 9, "2026-11-01T13:00:00Z")
    kit.tag(13, 9, "2026-11-01T13:00:00Z")
    kit_sync.run(now=NOW)
    assert _rows(db)["toodle:sub:9"]["channel"] == "organic"


def test_a_channel_tag_seen_on_a_later_run_fills_an_unknown_channel(db, kit):
    kit.tag(11, 8, "2026-11-02T11:55:00Z", "c@example.com")      # toodle, 5 minutes before the run
    assert kit_sync.run(now=NOW)["status"] == "ok"
    assert _rows(db)["toodle:sub:8"]["channel"] == "unknown"
    kit.tag(12, 8, "2026-11-02T12:01:00Z", "c@example.com")      # meta_ad, a minute after the run started
    out = kit_sync.run(now=NOW + timedelta(hours=1))
    row = _rows(db)["toodle:sub:8"]
    assert row["channel"] == "meta" and row["tags"] == ["meta_ad", "toodle"]
    assert row["occurred_at"] == datetime(2026, 11, 2, 11, 55, tzinfo=timezone.utc)
    assert (out["detail"]["inserted"], out["detail"]["relabelled"]) == (0, 1)
    # a channel tag that comes once the Toodle tag is out of the window: the earliest time stays
    kit.tag(11, 9, "2026-11-02T11:56:00Z")
    kit_sync.run(now=NOW + timedelta(hours=2))
    db.set_source("kit", synced_through="2026-11-02T16:00:00Z")
    kit.tag(13, 9, "2026-11-02T16:30:00Z")
    out = kit_sync.run(now=NOW + timedelta(hours=5))
    assert out["window_start"] == "2026-11-02T15:00:00+00:00"
    row = _rows(db)["toodle:sub:9"]
    assert row["channel"] == "organic" and row["occurred_at"] == datetime(2026, 11, 2, 11, 56, tzinfo=timezone.utc)


def test_a_rerun_lands_on_the_same_rows(db, kit):
    kit.tag(11, 1, "2026-11-02T11:00:00Z", "a@example.com")
    kit.tag(12, 1, "2026-11-02T11:00:02Z", "a@example.com")
    kit.tag(11, 2, "2026-11-02T11:30:00Z", "b@example.com")
    kit_sync.run(now=NOW)
    before = {k: {f: v for f, v in r.items() if f != "updated_at"} for k, r in _rows(db).items()}
    out = kit_sync.run(now=NOW + timedelta(minutes=30))
    assert out["status"] == "ok" and out["rows_written"] == 0
    assert (out["detail"]["inserted"], out["detail"]["relabelled"]) == (0, 2)
    after = {k: {f: v for f, v in r.items() if f != "updated_at"} for k, r in _rows(db).items()}
    assert after == before                                         # no second opt-in, nothing changed
    assert ledger.board_day(date(2026, 11, 2))["optins"]["total"] == 2


def test_later_runs_read_from_the_watermark_minus_an_hour_and_never_move_it_back(db, kit):
    kit_sync.run(now=NOW)
    out = kit_sync.run(now=NOW + timedelta(hours=1))
    assert out["window_start"] == (NOW - timedelta(minutes=10) - timedelta(hours=1)).isoformat()
    last = kit.calls_to("/v4/tags/11/subscribers")[-1]["query"]
    assert (last["tagged_after"], last["tagged_before"]) == ("2026-10-31", "2026-11-04")
    assert db.sources["kit"]["synced_through"] == NOW + timedelta(minutes=50)
    assert kit_sync.run(now=NOW + timedelta(minutes=30))["status"] == "ok"    # started earlier, finished later
    assert db.sources["kit"]["synced_through"] == NOW + timedelta(minutes=50)
    assert db.sources["kit"]["measured_from"] == date(2026, 1, 1)             # set once, by the first run
    sets = [c for c in db.calls if c.method == "PATCH" and c.url.params.get("measured_from") == "is.null"]
    assert len(sets) == 1                                                     # later runs never send it


def test_days_widens_the_window_but_never_narrows_it(db, kit, monkeypatch):
    db.set_source("kit", measured_from="2026-01-01", synced_through="2026-11-02T06:00:00Z")
    assert kit_sync.run(now=NOW, days=7)["window_start"] == (NOW - timedelta(days=7)).isoformat()
    db.set_source("kit", synced_through="2026-10-20T06:00:00Z")      # far behind: days=1 must not skip the gap
    assert kit_sync.run(now=NOW + timedelta(hours=1), days=1)["window_start"] == "2026-10-20T05:00:00+00:00"


def test_a_tag_added_to_the_setting_later_reaches_past_days(db, kit, monkeypatch):
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:,meta_ad:meta")
    kit.add_tag(15, "toodle_lp2")                                   # a second opt-in tag, not configured yet
    kit.tag(11, 501, "2026-10-20T16:00:00Z")
    kit.tag(15, 502, "2026-10-20T17:00:00Z")                         # its only Toodle tag
    kit.tag(15, 503, "2026-10-20T18:00:00Z")
    kit.tag(12, 503, "2026-10-20T18:00:05Z")
    first = kit_sync.run(now=NOW)
    assert first["detail"]["tag_set"] == [[11, None], [12, "meta"]]    # what it read: ids and channels only
    assert ledger.board_day(date(2026, 10, 20))["optins"]["total"] == 2
    same = kit_sync.run(now=NOW + timedelta(hours=1))
    assert same["detail"]["from_backfill"] is False
    assert same["window_start"] == (NOW - timedelta(minutes=10) - timedelta(hours=1)).isoformat()
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:,meta_ad:meta,toodle_lp2:")
    out = kit_sync.run(now=NOW + timedelta(hours=2))
    assert out["status"] == "ok" and out["detail"]["from_backfill"] is True
    assert out["window_start"] == "2026-01-01T05:00:00+00:00"        # BOARD_BACKFILL_FROM again
    assert out["detail"]["tag_set"] == [[11, None], [12, "meta"], [15, None]]
    assert set(_rows(db)) == {"toodle:sub:501", "toodle:sub:502", "toodle:sub:503"}
    assert _rows(db)["toodle:sub:503"]["occurred_at"] == datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    assert ledger.board_day(date(2026, 10, 20))["optins"] == {"total": 3, "by_channel": {"unknown": 2, "meta": 1}}
    assert db.sources["kit"]["measured_from"] == date(2026, 1, 1)                # set by the first run only
    again = kit_sync.run(now=NOW + timedelta(hours=3))
    assert again["detail"]["from_backfill"] is False                              # read once, then as usual


def test_a_channel_tag_added_to_the_setting_later_labels_older_opt_ins(db, kit, monkeypatch):
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:")
    kit.tag(11, 601, "2026-10-15T16:00:00Z")
    kit.tag(12, 601, "2026-10-15T16:00:05Z")                        # meta_ad, not configured yet
    kit.tag(11, 602, "2026-03-10T16:00:00Z")                        # months back: past any `days` the page sends
    kit.tag(12, 602, "2026-03-10T16:00:01Z")
    kit_sync.run(now=NOW)
    assert {k: r["channel"] for k, r in _rows(db).items()} == {"toodle:sub:601": "unknown",
                                                               "toodle:sub:602": "unknown"}
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:,meta_ad:meta")
    out = kit_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok" and out["detail"]["from_backfill"] is True
    assert {k: r["channel"] for k, r in _rows(db).items()} == {"toodle:sub:601": "meta", "toodle:sub:602": "meta"}
    assert ledger.board_day(date(2026, 10, 15))["optins"] == {"total": 1, "by_channel": {"meta": 1}}


def test_a_changed_tag_setting_is_read_again_until_a_run_completes(db, kit, monkeypatch):
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:")
    kit_sync.run(now=NOW)
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:,meta_ad:meta")
    kit.fail_on["/v4/tags/12/subscribers"] = [(500, {"errors": ["Something went wrong"]}, {})] * 4
    failed = kit_sync.run(now=NOW + timedelta(hours=1))
    assert failed["status"] == "failed" and failed["detail"]["from_backfill"] is True
    out = kit_sync.run(now=NOW + timedelta(hours=2))                 # the last complete run read "toodle" only
    assert out["status"] == "ok" and out["detail"]["from_backfill"] is True
    assert out["window_start"] == "2026-01-01T05:00:00+00:00"


def test_without_a_recorded_tag_set_a_run_reads_from_the_watermark_as_before(db, kit):
    db.set_source("kit", measured_from="2026-01-01", synced_through="2026-11-02T06:00:00Z")
    old = db._rpc_board_claim_run("kit_sync", "a-run-from-before", "schedule", "kit")
    db.job_runs[old].update(status="ok", finished_at=NOW - timedelta(hours=6), detail={"tags_configured": ["toodle"]})
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["from_backfill"] is False
    assert out["window_start"] == "2026-11-02T05:00:00+00:00"        # the watermark minus an hour, as before
    assert out["detail"]["tag_set"] == [[11, None], [12, "meta"], [13, "organic"]]
    assert kit_sync.run(now=NOW + timedelta(hours=1))["detail"]["from_backfill"] is False   # its own record


def test_a_first_run_widened_by_days_measures_from_its_first_whole_day(db, kit, monkeypatch):
    monkeypatch.setenv("BOARD_BACKFILL_FROM", "2026-11-01")
    out = kit_sync.run(now=NOW, days=3)                               # from 08:00 on 30 Oct in New York
    assert out["window_start"] == (NOW - timedelta(days=3)).isoformat()
    assert db.sources["kit"]["measured_from"] == date(2026, 10, 31)


def test_a_sync_reads_kit_with_kit_dry_run_on(db, kit, monkeypatch):
    monkeypatch.setenv("KIT_DRY_RUN", "true")                  # it holds back writes to Kit only
    kit.tag(11, 1, "2026-11-02T11:00:00Z")
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and set(_rows(db)) == {"toodle:sub:1"}
    assert kit.calls and all(c["method"] == "GET" for c in kit.calls)


def test_the_new_york_day_decides_which_day_an_opt_in_counts_for(db, kit):
    kit.tag(11, 31, "2026-11-02T03:59:00Z")      # 22:59 on Sun 1 Nov (EST): 1 Nov
    kit.tag(12, 32, "2026-11-02T05:00:00Z")      # midnight on Mon 2 Nov: 2 Nov
    kit.tag(13, 33, "2026-11-01T04:00:00Z")      # midnight on Sun 1 Nov (EDT): 1 Nov
    kit.tag(11, 34, "2026-11-01T03:59:59Z")      # 23:59:59 on Sat 31 Oct
    assert kit_sync.run(now=NOW)["status"] == "ok"
    nov1 = ledger.board_day(date(2026, 11, 1))
    assert nov1["hours_in_day"] == 25
    assert nov1["optins"] == {"total": 2, "by_channel": {"unknown": 1, "organic": 1}}
    nov2 = ledger.board_day(date(2026, 11, 2))
    assert nov2["optins"] == {"total": 1, "by_channel": {"meta": 1}}
    assert ledger.board_day(date(2026, 10, 31))["optins"]["total"] == 1
    # synced to 11:50Z on 2 Nov: 1 Nov (ended 05:00Z) is final, 2 Nov is still partial
    assert {s["id"]: s["state"] for s in nov1["sources"]}["kit"] == "final"
    assert {s["id"]: s["state"] for s in nov2["sources"]}["kit"] == "partial"


# ─── Kit refusing, limiting or failing ──────────────────────────────────────

def test_kit_is_read_at_most_once_a_second(db, kit, monkeypatch):
    # Kit allows a key 120 requests a minute, shared with the Toodle capture, so a run paces its reads
    # one a second (the kit fixture raises the pace for the other tests). A fake clock: no real waiting.
    clock, sent_at = [1000.0], []

    def sleep(seconds):
        clock[0] += seconds

    def request(*args, **kwargs):
        sent_at.append(clock[0])
        return kit.request(*args, **kwargs)

    monkeypatch.setattr(kit_sync, "_RATE_PER_SEC", RATE_PER_SEC)
    monkeypatch.setattr(core_kit, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    monkeypatch.setattr(core_kit, "requests", SimpleNamespace(request=request,
                                                              RequestException=requests.RequestException))
    kit.tag(11, 1, "2026-11-02T11:00:00Z")
    assert kit_sync.run(now=NOW)["status"] == "ok"
    assert len(sent_at) == 4                                     # the tag list, then each of the 3 tags
    assert all(later - earlier >= 1.0 for earlier, later in zip(sent_at, sent_at[1:])), sent_at


def test_a_rate_limit_is_waited_out_and_retried(db, kit):
    kit.tag(11, 1, "2026-11-02T11:00:00Z")
    kit.fail_next = [(429, None, {"Retry-After": "7"}), (429, None, {}),
                     (503, {"errors": ["Service unavailable"]}, {"Retry-After": "120"})]
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and "toodle:sub:1" in _rows(db)
    assert kit.sleeps == [7.0, 4.0, 30.0]               # Retry-After, else 2, 4, 8 seconds; 30 at most
    assert out["detail"]["retries"] == 3


def test_a_rate_limit_that_does_not_end_fails_the_run_plainly(db, kit):
    db.set_source("kit", measured_from="2026-01-01", synced_through="2026-11-02T06:00:00Z")
    kit.fail_next = [(429, None, {})] * 4
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == "Kit is rate limiting this key (HTTP 429) after 3 retries; the next run tries again"
    assert kit.sleeps == [2.0, 4.0, 8.0] and len(kit.calls) == 4
    src = db.sources["kit"]
    assert src["synced_through"] == datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)
    assert src["last_error"] == out["error"]
    (run,) = db.runs("kit_sync")
    assert run["status"] == "failed" and run["finished_at"] is not None and run["error"] == out["error"]


def test_kit_unreachable_is_retried_then_fails_without_the_exception_text(db, kit, caplog):
    caplog.set_level(logging.DEBUG)
    kit.fail_next = [requests.ConnectionError(f"proxy refused {BASE}/tags?per_page=1000 for {KIT_KEY}")] * 4
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"] == "Kit could not be reached after 3 retries"
    assert KIT_KEY not in caplog.text and "proxy refused" not in json.dumps(db.runs("kit_sync"), default=str)


def test_a_refused_key_is_recorded_without_the_key(db, kit, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    wrong = "kit_FAKEwrongKey9f8e7d6c5b4a3f2e1d0c"
    monkeypatch.setenv("KIT_API_KEY", wrong)
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"] == "Kit refused the API key (HTTP 401): check KIT_API_KEY"
    (run,) = db.runs("kit_sync")
    assert db.sources["kit"]["last_error"] == out["error"] and run["error"] == out["error"]
    stored = json.dumps([out, run, db.sources["kit"]], default=str)
    assert wrong not in stored and "kit_said" not in run["detail"]     # Kit's 401 text repeats the key
    assert wrong not in caplog.text
    assert _rows(db) == {} and db.sources["kit"]["measured_from"] is None


def test_when_kit_refuses_status_all_each_state_is_read_instead(db, kit):
    kit.refuse_all = True
    kit.max_subscriber_page = 100                        # and a page limit below the documented one
    kit.tag(11, 1, "2026-11-02T11:00:00Z", state="active")
    kit.tag(11, 2, "2026-11-02T11:01:00Z", state="cancelled")
    kit.tag(12, 2, "2026-11-02T11:01:30Z", state="cancelled")
    kit.tag(11, 3, "2026-11-02T11:02:00Z", state="inactive")
    out = kit_sync.run(now=NOW)
    assert out["status"] == "ok" and set(_rows(db)) == {"toodle:sub:1", "toodle:sub:2", "toodle:sub:3"}
    assert _rows(db)["toodle:sub:2"]["channel"] == "meta"
    assert out["detail"]["query"] == "each state (Kit refused status=all)"
    first = kit.calls_to("/v4/tags/11/subscribers")
    assert [c["query"]["status"] for c in first] == ["all", *STATES]
    later = kit.calls_to("/v4/tags/12/subscribers")                  # status=all is not asked again
    assert [c["query"]["status"] for c in later] == list(STATES)
    assert all(c["query"]["per_page"] == "100" for c in first[1:] + later)


def test_a_query_kit_refuses_either_way_fails_the_run_and_keeps_kits_words_hidden(db, kit):
    kit.fail_on["/v4/tags/11/subscribers"] = [
        (422, {"errors": ["Status is not included in the list"]}, {}),
        (422, {"errors": [f"Tagged after is invalid for key {KIT_KEY}", ["cursor", _cursor(10) * 3]]}, {})]
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"] == 'Kit answered HTTP 422 for tag "toodle"'
    said = out["detail"]["kit_said"]
    assert said == ["Tagged after is invalid for key [hidden]", "cursor [hidden]"]
    assert KIT_KEY not in json.dumps(db.runs("kit_sync"), default=str)
    # a short key is hidden too, though it looks like no token
    short = {"errors": ["no access for kit_s1", "x" * 300, 42, None, "", "\x00\x07"]}
    assert kit_sync._kit_said(short, "kit_s1") == ["no access for [hidden]", "[hidden]", "42"]


def test_a_subscriber_without_a_tag_time_fails_the_run_rather_than_count_zero(db, kit):
    kit.tag(11, 1, "2026-11-02T11:00:00Z")
    kit.taggings[11].append({"id": 2, "email_address": "x@example.com", "state": "active"})
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == 'Kit listed a subscriber of tag "toodle" without an id or a tag time, so nothing was written'
    assert _rows(db) == {} and db.sources["kit"]["measured_from"] is None


def test_an_answer_in_another_shape_fails_the_run(db, kit):
    kit.fail_next = [(200, {"data": []}, {})]
    out = kit_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"] == "Kit answered the tag list in a shape the sync cannot read"


def test_one_run_at_a_time_and_a_database_outage_never_reaches_kit(db, kit):
    db._rpc_board_claim_run("kit_sync", "an-earlier-run", "schedule", "kit")       # still running
    out = kit_sync.run(now=NOW)
    assert out["status"] == "busy" and out["error"] == "another Kit sync is running" and kit.calls == []
    db.down = True
    out = kit_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "failed" and out["error"].startswith("database:") and kit.calls == []


def test_a_disabled_source_is_skipped_before_kit_is_read(db, kit):
    db.set_source("kit", enabled=False)
    out = kit_sync.run(now=NOW)
    assert out["status"] == "skipped" and out["error"] == "the kit source is disabled" and kit.calls == []
    (run,) = db.runs("kit_sync")
    assert run["status"] == "skipped"
