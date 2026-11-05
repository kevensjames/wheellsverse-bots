"""SiteBoost replies from Instantly: the read (core.siteboost_instantly.list_replies)
and the connector (core/board/connectors/instantly_sync.py). One lead row per
received email; board_day counts distinct prospects per New York day.

No network: Instantly is FakeInstantly below, mounted as a requests adapter,
with a clock that moves when the code sleeps. Supabase is FakeBoardDB
(tests/board_fakes.py)."""
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from core import siteboost_instantly as si
from core.board import ledger
from core.board.connectors import instantly_sync
from tests import board_fakes as bf

KEY = "ZmFrZS1p" "bnN0YW50bHkta2V5LWZvci1ib2FyZC10ZXN0czpub3QtYS1zZWNyZXQ="   # fake, made up for tests; split so secret scanners skip it
CAMPAIGN = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
CAMPAIGN_2 = "6c1e7a52-90d4-4f3b-8e2a-1b2c3d4e5f60"     # an older SiteBoost campaign, still getting replies
OTHER = "9b2d7c1e-0f4a-4e8b-a1c3-5d6e7f8a9b0c"          # a campaign that is not SiteBoost's
OURS = "jay@mail.siteboost.example"                     # our sending mailbox (eaccount)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)  # 07:00 on Mon 2 Nov in New York
BACKFILL = "2026-01-01T05:00:00.000Z"                   # midnight in New York on 1 Jan 2026
WATERMARK = NOW - timedelta(minutes=5)
ALLOWED_PARAMS = {"campaign_id", "email_type", "mode", "limit", "min_timestamp_created",
                  "max_timestamp_created", "starting_after"}
NO_CAMPAIGNS = "no SiteBoost campaigns: set BOARD_SITEBOOST_CAMPAIGN_IDS to every SiteBoost campaign id, comma-separated"
RAW_KEYS = {"message_id", "thread_id", "lead_id", "ue_type", "i_status", "is_auto_reply", "auto_reply_by",
            "timestamp_email", "timestamp_created", "time_source"}


# ─── the fake Instantly API ─────────────────────────────────────────────────

def ts(iso: str) -> str:
    """'2026-11-01T13:00:00Z' as Instantly writes a time: milliseconds and a Z."""
    at = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _uuid(text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, text))


def received(eid, at, lead="p1@shop.example", *, campaign=CAMPAIGN, subject="Re: Jay — quick fix idea for Shop Co",
             auto=0, i_status=1, sender=None, stored=None, **fields) -> dict:
    """A prospect's reply as GET /api/v2/emails lists it (the official SDK's
    Email model), body included. `at` is the email's own time; `stored`, when
    Instantly stored it (default: the same)."""
    sender = lead if sender is None else sender
    email = {"id": eid, "timestamp_created": ts(stored or at), "timestamp_email": ts(at),
             "message_id": f"<{eid}.reply@mx.shop.example>", "subject": subject,
             "from_address_email": sender, "to_address_email_list": OURS, "cc_address_email_list": None,
             "bcc_address_email_list": None, "reply_to": None,
             "body": {"text": "Sounds good. Call me at 555-0100.", "html": "<p>Sounds good. Call me at 555-0100.</p>"},
             "organization_id": _uuid("org"), "campaign_id": campaign, "subsequence_id": None, "list_id": None,
             "lead": lead, "lead_id": _uuid(f"lead:{lead}"), "eaccount": OURS, "ue_type": 2, "step": None,
             "is_unread": 1, "is_auto_reply": auto, "reminder_ts": None, "ai_interest_value": 0.9,
             "ai_assisted": 0, "is_focused": 1, "i_status": i_status, "thread_id": _uuid(f"thread:{lead}"),
             "content_preview": "Sounds good. Call me at 555-0100.", "attachment_json": None,
             "from_address_json": [{"address": sender, "name": "Pat"}],
             "to_address_json": [{"address": OURS, "name": "Jay"}], "cc_address_json": None, "ai_agent_id": None}
    email.update(fields)
    return email


def sent(eid, at, lead="p1@shop.example", *, campaign=CAMPAIGN) -> dict:
    """One of our own campaign emails, as the same endpoint lists it."""
    return {**received(eid, at, lead, campaign=campaign, subject="Jay — quick fix idea for Shop Co", i_status=None),
            "from_address_email": OURS, "to_address_email_list": lead, "ue_type": 1, "step": "0_0_0",
            "is_unread": 0, "from_address_json": [{"address": OURS, "name": "Jay"}],
            "to_address_json": [{"address": lead, "name": "Pat"}]}


def _answer(request, status: int, body=None, headers=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.reason = HTTPStatus(status).phrase
    r.headers = CaseInsensitiveDict({"Content-Type": "application/json", **(headers or {})})
    r._content = b"" if body is None else json.dumps(body).encode()
    r.encoding = "utf-8"
    r.url = request.url
    r.request = request
    return r


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Clock:
    """time.monotonic and time.sleep for core.siteboost_instantly: sleeping moves the clock."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += max(0.0, seconds)


class FakeInstantly:
    """GET /api/v2/emails as the official SDK describes it: the filters
    campaign_id, email_type and min/max_timestamp_created (both ends
    inclusive here), newest first, `limit` up to 100, an opaque cursor in
    next_starting_after, and 429 after 20 calls in a minute. Every other
    method or path answers 404. Its 401 and error bodies quote the key it was
    sent, so the board must never pass them on."""

    def __init__(self, clock: Clock, key: str = KEY):
        self.clock, self.key = clock, key
        self.emails: list[tuple[str, dict]] = []      # (received or sent, the email)
        self.calls: list[requests.PreparedRequest] = []
        self.call_times: list[float] = []
        self.timeouts: list = []
        self.fail_next: list = []        # one per call: a status, (status, headers), or an exception to raise
        self.page_size = 100
        self.honour_type = True          # False: received and sent mixed, as if email_type were ignored
        self.honour_campaign = True      # False: every campaign's emails, as if campaign_id were ignored
        self.last_page = "absent"        # the last page's cursor: absent, null, empty, repeat, or extra
        self._cursors: dict[str, int] = {}

    def add(self, *emails: dict, kind: str = "received") -> "FakeInstantly":
        self.emails.extend((kind, e) for e in emails)
        return self

    def params(self, i: int = -1) -> dict:
        """The query of call i, one value per name (a repeated name fails the test)."""
        query = parse_qs(urlsplit(self.calls[i].url).query, keep_blank_values=True)
        assert all(len(v) == 1 for v in query.values()), query
        return {k: v[0] for k, v in query.items()}

    def _cursor(self, offset: int) -> str:
        token = f"c+{len(self._cursors)}/{offset}=="     # '+', '/' and '=' must arrive as sent
        self._cursors[token] = offset
        return token

    def _wanted(self, kind: str, e: dict, q: dict) -> bool:
        if self.honour_type and q.get("email_type") and q["email_type"] != kind:
            return False
        if self.honour_campaign and q.get("campaign_id") and e.get("campaign_id") != q["campaign_id"]:
            return False
        created = _instant(e["timestamp_created"]) if e.get("timestamp_created") else None
        if created is not None and "min_timestamp_created" in q and created < _instant(q["min_timestamp_created"]):
            return False
        if created is not None and "max_timestamp_created" in q and created > _instant(q["max_timestamp_created"]):
            return False
        return True

    def handle(self, request: requests.PreparedRequest, timeout) -> requests.Response:
        self.calls.append(request)
        self.timeouts.append(timeout)
        url = urlsplit(request.url)
        if url.scheme != "https" or url.hostname != "api.instantly.ai":
            return _answer(request, 404, {"message": "unknown host"})
        if request.method != "GET" or url.path != "/api/v2/emails":
            return _answer(request, 404, {"statusCode": 404, "error": "Not Found", "message": "Route not found"})
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {self.key}":
            return _answer(request, 401, {"statusCode": 401, "error": "Unauthorized",
                                          "message": f"Invalid API key: {auth}"})
        now = self.clock.now
        recent = [t for t in self.call_times if t > now - 60]
        self.call_times.append(now)
        if len(recent) >= 20:
            return _answer(request, 429, {"statusCode": 429, "error": "Too Many Requests",
                                          "message": "Rate limit exceeded"})
        if self.fail_next:
            fail = self.fail_next.pop(0)
            if isinstance(fail, Exception):
                raise fail
            status, headers = fail if isinstance(fail, tuple) else (fail, {})
            return _answer(request, status, {"statusCode": status, "error": HTTPStatus(status).phrase,
                                             "message": f"refused key {auth}"}, headers)
        q = self.params()
        rows = sorted((e for kind, e in self.emails if self._wanted(kind, e, q)),
                      key=lambda e: (e.get("timestamp_created") or "", e.get("id") or ""), reverse=True)
        start = 0
        if "starting_after" in q:
            if q["starting_after"] not in self._cursors:
                return _answer(request, 400, {"statusCode": 400, "error": "Bad Request", "message": "bad cursor"})
            start = self._cursors[q["starting_after"]]
        page = rows[start:start + min(int(q.get("limit", "10")), 100, self.page_size)]
        body: dict = {"items": json.loads(json.dumps(page))}
        end = start + len(page)
        if end < len(rows):
            body["next_starting_after"] = self._cursor(end)
        elif self.last_page == "null":
            body["next_starting_after"] = None
        elif self.last_page == "empty":
            body["next_starting_after"] = ""
        elif self.last_page == "repeat":
            body["next_starting_after"] = q.get("starting_after") or self._cursor(end)
        elif self.last_page == "extra":
            body["next_starting_after"] = self._cursor(end)           # one more page, an empty one
        return _answer(request, 200, body)


class FakeAdapter(BaseAdapter):
    """requests' transport, answered by FakeInstantly: nothing leaves the process."""

    def __init__(self, fake: FakeInstantly):
        super().__init__()
        self.fake = fake

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        return self.fake.handle(request, timeout)

    def close(self):
        pass


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(si, "_clock", c.monotonic)
    monkeypatch.setattr(si, "_sleep", c.sleep)
    monkeypatch.setattr(si, "_last_call", None)
    return c


@pytest.fixture
def api(monkeypatch, clock):
    fake = FakeInstantly(clock)
    monkeypatch.setattr(si, "_adapter", FakeAdapter(fake))
    monkeypatch.setenv("INSTANTLY_API_KEY", KEY)
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", CAMPAIGN)
    monkeypatch.delenv("BOARD_BACKFILL_FROM", raising=False)
    return fake


@pytest.fixture
def db(monkeypatch):
    monkeypatch.delenv("BOARD_CPL_DAYS", raising=False)
    monkeypatch.delenv("BOARD_CPL_STOP_CENTS", raising=False)
    return bf.install_board(monkeypatch)


def _rows(db) -> dict:
    return db.lead_rows("instantly")


def _replies(day: str) -> dict:
    """board_day's replies block: what the board and the morning message show."""
    return ledger.board_day(date.fromisoformat(day))["replies"]


def _synced(db, through=WATERMARK) -> None:
    """The instantly source as a complete run of CAMPAIGN leaves it."""
    db.set_source("instantly", measured_from="2026-01-01", synced_through=through,
                  account_ref=f"campaigns:{CAMPAIGN}")


def _plan_replies() -> list[dict]:
    """The plan's replies around Sun 1 Nov 2026 (the morning message in
    replica/architecture.md): one prospect who replied twice, one auto-reply,
    another prospect 4 days earlier, and one 7 days back (outside the week)."""
    return [received("em1", "2026-11-01T13:00:00Z", "p1@shop.example"),
            received("em2", "2026-11-01T18:00:00Z", "P1@Shop.example", subject="Re: Re: Jay — quick fix idea"),
            received("em3", "2026-11-01T19:00:00Z", "p2@shop.example", auto=1, i_status=0,
                     subject="Automatic reply: Re: Jay — quick fix idea for Shop Co"),
            received("em4", "2026-10-28T19:00:00Z", "p3@shop.example"),
            received("em5", "2026-10-25T12:00:00Z", "p4@shop.example")]


# ─── a run: claim, read, write, move the watermark ──────────────────────────

def test_the_first_run_backfills_one_row_per_received_email_and_sets_measured_from(db, api):
    api.add(*_plan_replies())
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "ok", out
    rows = _rows(db)
    assert set(rows) == {"em1", "em2", "em3", "em4", "em5"}
    em2 = rows["em2"]
    assert (em2["kind"], em2["funnel"], em2["channel"], em2["campaign_ref"]) == \
        ("reply", "siteboost", "outreach", CAMPAIGN)
    assert em2["email"] == "p1@shop.example"                                  # the same prospect as em1
    assert em2["occurred_at"] == datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
    assert rows["em3"]["is_auto_reply"] and not rows["em1"]["is_auto_reply"]
    assert len(api.calls) == 1
    q = api.params(0)
    assert (q["min_timestamp_created"], q["max_timestamp_created"]) == (BACKFILL, "2026-11-02T12:00:00.000Z")
    src = db.sources["instantly"]
    assert src["measured_from"] == date(2026, 1, 1) and src["synced_through"] == WATERMARK
    assert src["last_error"] is None and src["last_ok_at"] is not None
    assert src["account_ref"] == f"campaigns:{CAMPAIGN}"                     # the campaigns it read
    (run,) = db.runs("instantly_sync")
    assert run["status"] == "ok" and run["source_id"] == "instantly" and run["rows_written"] == 5
    assert run["detail"]["from_backfill"] is True
    assert run["covered_until"] == WATERMARK
    assert run["detail"]["emails"] == 5 and run["detail"]["automatic_by"] == {"instantly": 1}
    assert all(r["job_run_id"] == run["id"] for r in rows.values())
    assert out["window_start"] == "2026-01-01T05:00:00+00:00" and out["covered_until"] == WATERMARK.isoformat()


def test_the_read_asks_for_received_emails_of_one_campaign_and_nothing_else(db, api, monkeypatch):
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", f"{CAMPAIGN}, {CAMPAIGN_2}")
    api.add(received("em1", "2026-11-01T13:00:00Z"), received("em9", "2026-10-30T13:00:00Z", campaign=CAMPAIGN_2))
    assert instantly_sync.run(now=NOW)["status"] == "ok"
    assert set(_rows(db)) == {"em1", "em9"} and _rows(db)["em9"]["campaign_ref"] == CAMPAIGN_2
    assert [api.params(i)["campaign_id"] for i in range(len(api.calls))] == [CAMPAIGN, CAMPAIGN_2]
    for i, call in enumerate(api.calls):
        assert call.method == "GET" and call.url.startswith("https://api.instantly.ai/api/v2/emails?")
        assert call.headers["Authorization"] == f"Bearer {KEY}"
        assert api.params(i) == {"campaign_id": api.params(i)["campaign_id"], "email_type": "received",
                                 "mode": "emode_all", "limit": "100", "min_timestamp_created": BACKFILL,
                                 "max_timestamp_created": "2026-11-02T12:00:00.000Z"}
    assert api.timeouts == [30.0, 30.0]
    # never the filters that would hide replies, nor a sort that is not the default
    for name in ("is_unread", "i_status", "latest_of_thread", "preview_only", "sort_order", "search", "lead"):
        assert all(name not in api.params(i) for i in range(len(api.calls)))


def test_pages_are_followed_with_the_cursor_exactly_as_sent(db, api):
    api.page_size = 2
    api.add(*[received(f"em{i}", f"2026-11-01T1{i}:00:00Z", f"p{i}@shop.example") for i in range(5)])
    assert instantly_sync.run(now=NOW)["status"] == "ok"
    assert len(_rows(db)) == 5
    assert len(api.calls) == 3                                    # 2 + 2 + 1
    cursors = [api.params(i).get("starting_after") for i in range(3)]
    assert cursors[0] is None and cursors[1].startswith("c+") and cursors[1].endswith("==")
    assert cursors[2] != cursors[1] and "/" in cursors[2]
    assert db.runs("instantly_sync")[0]["detail"]["pages"] == 3


@pytest.mark.parametrize("last_page, calls", [("absent", 2), ("null", 2), ("empty", 2), ("repeat", 2),
                                               ("extra", 3)])
def test_paging_stops_at_an_empty_page_or_no_new_cursor(db, api, last_page, calls):
    api.page_size, api.last_page = 2, last_page
    api.add(*[received(f"em{i}", f"2026-11-01T1{i}:00:00Z", f"p{i}@shop.example") for i in range(3)])
    assert instantly_sync.run(now=NOW)["status"] == "ok"
    assert len(api.calls) == calls and len(_rows(db)) == 3


def test_endless_pages_fail_the_run_instead_of_reading_forever(db, api, monkeypatch):
    monkeypatch.setattr(si, "MAX_PAGES", 3)
    api.page_size = 1
    api.add(*[received(f"em{i}", f"2026-11-01T1{i}:00:00Z", f"p{i}@shop.example") for i in range(5)])
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"] == f"Instantly kept sending pages for campaign {CAMPAIGN[:8]}: " \
                                                         "stopped after 3"
    assert _rows(db) == {} and db.sources["instantly"]["synced_through"] is None


def test_only_received_emails_count_even_when_sent_ones_are_mixed_in(db, api):
    api.honour_type = False
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    api.add(sent("out1", "2026-11-01T12:00:00Z"), sent("out2", "2026-11-01T12:05:00Z", "p9@shop.example"),
            {**sent("out3", "2026-11-01T12:10:00Z"), "email_type": "sent"}, kind="sent")
    out = instantly_sync.run(now=NOW)
    assert set(_rows(db)) == {"em1"}
    assert out["detail"]["sent_by_us"] == 3 and out["detail"]["emails"] == 1
    assert _replies("2026-11-01") == {"people": 1, "auto_replies": 0, "people_7d": 1}


def test_another_campaigns_email_and_a_manual_one_are_left_out(db, api):
    api.honour_campaign = False
    api.add(received("em1", "2026-11-01T13:00:00Z"), received("em2", "2026-11-01T14:00:00Z", campaign=OTHER),
            received("em3", "2026-11-01T15:00:00Z", campaign=None))
    out = instantly_sync.run(now=NOW)
    assert set(_rows(db)) == {"em1"} and out["detail"]["other_campaign"] == 2


def test_an_email_created_at_the_runs_start_waits_for_the_next_run(db, api):
    api.add(received("em1", "2026-11-02T12:00:00Z"))               # max_timestamp_created is inclusive here
    out = instantly_sync.run(now=NOW)
    assert out["detail"]["outside_window"] == 1 and _rows(db) == {}
    assert instantly_sync.run(now=NOW + timedelta(hours=1))["detail"]["inserted"] == 1
    assert set(_rows(db)) == {"em1"}


# ─── automatic replies ──────────────────────────────────────────────────────

def test_an_email_is_automatic_by_instantlys_flag_its_out_of_office_status_or_its_subject(db, api):
    api.add(received("flag1", "2026-11-01T13:00:00Z", "a@shop.example", auto=1),
            received("flag0_subject", "2026-11-01T13:05:00Z", "b@shop.example", auto=0,
                     subject="Automatic reply: Re: Jay — quick fix idea for Shop Co"),
            received("flag0_ooo", "2026-11-01T13:06:00Z", "g@shop.example", auto=0, i_status=0),
            received("nf_subject", "2026-11-01T13:10:00Z", "c@shop.example", auto=None,
                     subject="Out of Office: Re: Jay — quick fix idea for Shop Co"),
            received("nf_ooo", "2026-11-01T13:15:00Z", "d@shop.example", auto=None, i_status=0),
            received("flag0_office", "2026-11-01T13:20:00Z", "e@shop.example", auto=0,
                     subject="Re: Jay — quick fix idea for Main Street Dental Office"),
            received("nf_fresh", "2026-11-01T13:25:00Z", "f@shop.example", auto=None,
                     subject="Question about our office website"))
    out = instantly_sync.run(now=NOW)
    rows = _rows(db)
    assert {k: (r["is_auto_reply"], r["raw"]["auto_reply_by"]) for k, r in rows.items()} == {
        "flag1": (True, "instantly"), "flag0_subject": (True, "subject"), "flag0_ooo": (True, "out_of_office"),
        "nf_subject": (True, "subject"), "nf_ooo": (True, "out_of_office"), "flag0_office": (False, None),
        "nf_fresh": (False, None)}
    assert out["detail"]["automatic"] == 5
    assert out["detail"]["automatic_by"] == {"instantly": 1, "subject": 2, "out_of_office": 2}
    assert _replies("2026-11-01") == {"people": 2, "auto_replies": 5, "people_7d": 2}


@pytest.mark.parametrize("fields, reason", [
    ({"is_auto_reply": True}, "instantly"),
    ({"is_auto_reply": False, "i_status": 0}, "out_of_office"),                # Instantly's Out of Office status
    ({"is_auto_reply": False, "subject": "Automatic reply: Re: Jay — quick fix idea"}, "subject"),
    ({"is_auto_reply": False, "subject": "Out of Office: Re: Jay — quick fix idea"}, "subject"),
    ({"is_auto_reply": False, "i_status": 1, "subject": "Re: Jay — quick fix idea for Main Street Dental Office"},
     None),                                                                    # a real reply that mentions an office
    ({"is_auto_reply": False, "i_status": 1, "subject": "Back in the office Monday - let's talk"}, None),
    ({"is_auto_reply": False, "i_status": -1, "subject": "Re: Jay"}, None),     # not interested is still a reply
    ({"is_auto_reply": None, "i_status": None, "subject": "Re: Jay"}, None),
])
def test_the_flag_the_out_of_office_status_or_the_subject_makes_an_email_automatic(fields, reason):
    assert instantly_sync.auto_reply_reason({"subject": "Re: Jay", **fields}) == reason


@pytest.mark.parametrize("subject", [
    "Automatic reply: Re: Jay — quick fix idea for Shop Co", "Out of Office: Re: Jay — quick fix idea",
    "Out of the office until Monday", "Out-of-Office", "Auto-Reply: Re: Jay", "AutoReply: Jay", "Autoreply",
    "Auto Response", "[Auto-Reply] Re: Jay — closing the file?", "Out of Office AutoReply: Re: Jay",
    "OOO until 11/9", "Vacation responder", "Vacation auto-reply", "Away from the office", "Away from my desk",
    "Abwesenheitsnotiz: AW: Jay — quick fix idea", "Automatische Antwort: AW: Jay", "Nicht im Büro",
    "Außer Haus bis Montag", "Réponse automatique : RE : Jay", "Absent du bureau", "Message d’absence",
    "Respuesta automática: RE: Jay", "Fuera de la oficina", "Mensaje de ausencia",
])
def test_the_subject_check_finds_automatic_replies(subject):
    assert instantly_sync.auto_reply_reason({"subject": subject, "is_auto_reply": None}) == "subject"


@pytest.mark.parametrize("subject", [
    "Re: Jay — quick fix idea for Main Street Dental Office",       # 'office' in a normal reply
    "Re: Jay — quick fix idea for Out of Office Supplies",          # the company's name, in our own subject
    "RE: Jay — closing the file?", "Re: Re: Jay — quick fix idea", "AW: Jay — quick fix idea",
    "Question about our office website", "Back in the office Monday - let's talk",
    "Away from home this week - call me Monday", "Ooo, I like this", "Re: Automatic reply",
    "Interested", "", None,
])
def test_the_subject_check_leaves_a_real_reply_alone(subject):
    for flag in (None, False):
        assert instantly_sync.auto_reply_reason({"subject": subject, "is_auto_reply": flag}) is None


@pytest.mark.parametrize("fields, reason", [
    ({"from_address": "mailer-daemon@googlemail.com"}, "sender"),
    ({"from_address": "MAILER-DAEMON@mx.shop.example"}, "sender"),
    ({"from_address": "postmaster@shop.example"}, "sender"),
    ({"from_address": "noreply@shop.example"}, "sender"),
    ({"from_address": "no-reply+ticket@help.shop.example"}, "sender"),
    ({"from_address": "donotreply@shop.example"}, "sender"),
    ({"subject": "Undeliverable: Jay — quick fix idea for Shop Co"}, "bounce"),
    ({"subject": "Delivery Status Notification (Failure)"}, "bounce"),
    ({"subject": "Undelivered Mail Returned to Sender"}, "bounce"),
    ({"subject": "Mail delivery failed: returning message to sender"}, "bounce"),
    ({"subject": "Unzustellbar: Jay — quick fix idea"}, "bounce"),
    ({"subject": "Non remis : Jay — quick fix idea"}, "bounce"),
    ({"subject": "No se puede entregar: Jay — quick fix idea"}, "bounce"),
])
def test_a_bounce_or_a_machine_sender_is_automatic_whatever_the_flag_says(fields, reason):
    for flag in (False, None, True):
        assert instantly_sync.auto_reply_reason({"is_auto_reply": flag, "subject": "Re: Jay", **fields}) == reason
    assert instantly_sync.auto_reply_reason({"is_auto_reply": False, "subject": "Re: Undeliverable",
                                             "from_address": "pat@shop.example"}) is None


def test_a_bounce_is_counted_as_an_automatic_reply_not_a_prospect(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z", "p1@shop.example"),
            received("b1", "2026-11-01T13:01:00Z", "p2@shop.example", auto=0, sender="mailer-daemon@googlemail.com",
                     subject="Delivery Status Notification (Failure)"))
    instantly_sync.run(now=NOW)
    assert _rows(db)["b1"]["is_auto_reply"] and _rows(db)["b1"]["email"] == "p2@shop.example"
    assert _replies("2026-11-01") == {"people": 1, "auto_replies": 1, "people_7d": 1}


def test_an_email_marked_automatic_on_a_later_run_stays_automatic(db, api):
    late = received("em1", "2026-11-01T13:00:00Z", auto=None, subject="Re: Jay — quick fix idea")
    api.add(late)
    instantly_sync.run(now=NOW)
    assert not _rows(db)["em1"]["is_auto_reply"]
    late["is_auto_reply"] = 1                                       # Instantly flags it later
    out = instantly_sync.run(now=NOW + timedelta(hours=1))
    assert out["detail"]["relabelled"] == 1 and _rows(db)["em1"]["is_auto_reply"]
    assert _replies("2026-11-01")["people"] == 0


# ─── counting: prospects, the week, the New York day ────────────────────────

def test_two_replies_from_one_prospect_count_once_and_auto_replies_are_left_out(db, api):
    api.add(*_plan_replies())
    instantly_sync.run(now=NOW)
    assert _replies("2026-11-01") == {"people": 1, "auto_replies": 1, "people_7d": 2}
    assert db.sources["instantly"]["synced_through"] >= datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)
    states = {s["id"]: s["state"] for s in ledger.board_day(date(2026, 11, 1))["sources"]}
    assert states["instantly"] == "final"


def test_the_seven_day_count_counts_each_prospect_once_over_seven_new_york_days(db, api):
    api.add(received("a1", "2026-10-26T15:00:00Z", "a@shop.example"),           # day 1 of the 7
            received("a2", "2026-11-01T15:00:00Z", "a@shop.example"),           # day 7, the same prospect
            received("b1", "2026-10-29T15:00:00Z", "b@shop.example"),
            received("c1", "2026-10-25T15:00:00Z", "c@shop.example"),           # one day too early
            received("d1", "2026-10-30T15:00:00Z", "d@shop.example", auto=1))   # automatic: never counted
    instantly_sync.run(now=NOW)
    assert _replies("2026-11-01") == {"people": 1, "auto_replies": 0, "people_7d": 2}
    assert _replies("2026-10-31") == {"people": 0, "auto_replies": 0, "people_7d": 3}       # a, b and c
    assert _replies("2026-10-30") == {"people": 0, "auto_replies": 1, "people_7d": 3}


def test_replies_land_on_new_york_days_through_the_25_hour_day(db, api):
    api.add(received("e1", "2026-11-01T03:59:00Z", "a@shop.example"),     # 23:59 EDT, Sat 31 Oct
            received("e2", "2026-11-01T04:00:00Z", "b@shop.example"),     # 00:00 EDT, Sun 1 Nov
            received("e3", "2026-11-02T04:30:00Z", "c@shop.example"),     # 23:30 EST, still Sun 1 Nov
            received("e4", "2026-11-02T05:00:00Z", "d@shop.example"))     # 00:00 EST, Mon 2 Nov
    instantly_sync.run(now=NOW)
    assert {k: str(r["local_day"]) for k, r in _rows(db).items()} == {
        "e1": "2026-10-31", "e2": "2026-11-01", "e3": "2026-11-01", "e4": "2026-11-02"}
    assert [_replies(d)["people"] for d in ("2026-10-31", "2026-11-01", "2026-11-02")] == [1, 2, 1]


def test_a_reply_counts_on_the_day_instantly_stored_it(db, api):
    api.add(received("em1", "2026-11-02T04:58:00Z", stored="2026-11-02T05:03:00Z"))   # 23:58, stored 00:03
    instantly_sync.run(now=NOW)
    row = _rows(db)["em1"]
    assert str(row["local_day"]) == "2026-11-02" and row["raw"]["time_source"] == "timestamp_created"
    assert row["occurred_at"] == datetime(2026, 11, 2, 5, 3, tzinfo=timezone.utc)
    assert (row["raw"]["timestamp_created"], row["raw"]["timestamp_email"]) == \
        ("2026-11-02T05:03:00+00:00", "2026-11-02T04:58:00+00:00")             # the sent time is kept, in raw


def test_a_day_marked_final_never_changes_when_a_reply_is_stored_late(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z", "p1@shop.example"))
    instantly_sync.run(now=datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc))      # 00:30 on 2 Nov in New York

    def state(day):
        found = ledger.board_day(date.fromisoformat(day))
        return found["replies"]["people"], {s["id"]: s["state"] for s in found["sources"]}["instantly"]
    assert state("2026-11-01") == (1, "final")
    # sent at 23:58 on 1 Nov, stored by Instantly at 01:00 on 2 Nov, after 1 Nov was final
    api.add(received("em2", "2026-11-02T04:58:00Z", "p2@shop.example", stored="2026-11-02T06:00:00Z"))
    instantly_sync.run(now=datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc))
    assert state("2026-11-01") == (1, "final")                                     # unchanged
    assert _replies("2026-11-02")["people"] == 1 and str(_rows(db)["em2"]["local_day"]) == "2026-11-02"


def test_a_reply_is_dated_when_instantly_stored_it():
    stored = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
    for sent_at in (stored - timedelta(minutes=3), stored + timedelta(minutes=5), stored - timedelta(days=3), None):
        assert instantly_sync.reply_time({"timestamp_email": sent_at, "timestamp_created": stored}) == \
            (stored, "timestamp_created")
    assert instantly_sync.reply_time({"timestamp_email": stored, "timestamp_created": None}) == (None, None)
    assert instantly_sync.reply_time({}) == (None, None)


def test_the_prospect_is_the_lead_else_the_sender_never_our_mailbox(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z", None, sender="Pat Doe <Pat@Shop.example>"),
            received("em2", "2026-11-01T14:00:00Z", None, sender=OURS, to_address_email_list=OURS),
            received("em3", "2026-11-01T15:00:00Z", "lead@shop.example", sender="colleague@shop.example"))
    instantly_sync.run(now=NOW)
    rows = _rows(db)
    assert (rows["em1"]["email"], rows["em2"]["email"], rows["em3"]["email"]) == \
        ("pat@shop.example", None, "lead@shop.example")
    assert _replies("2026-11-01")["people"] == 3                     # em2 counts as a prospect of its own


def test_raw_keeps_ids_codes_and_times_never_the_body_subject_or_an_address(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z", subject="Re: Jay — quick fix idea for Shop Co"))
    instantly_sync.run(now=NOW)
    raw = _rows(db)["em1"]["raw"]
    assert set(raw) == RAW_KEYS
    assert raw["message_id"] == "<em1.reply@mx.shop.example>" and raw["ue_type"] == 2 and raw["i_status"] == 1
    assert raw["is_auto_reply"] == 0 and raw["time_source"] == "timestamp_created"
    text = json.dumps(raw)
    for secret in ("p1@shop.example", OURS, "Sounds good", "555-0100", "quick fix idea", "Shop Co"):
        assert secret not in text


# ─── idempotence, the watermark and measured_from ───────────────────────────

def test_a_rerun_lands_on_the_same_rows(db, api):
    api.add(*_plan_replies())
    instantly_sync.run(now=NOW)

    def snapshot():
        return {k: {c: v for c, v in r.items() if c != "updated_at"} for k, r in _rows(db).items()}

    before = snapshot()
    out = instantly_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok"
    # the 48-hour overlap re-reads the three replies of 1 Nov: no new row, nothing changed
    assert (out["detail"]["inserted"], out["detail"]["relabelled"], out["rows_written"]) == (0, 3, 0)
    assert snapshot() == before
    assert api.params()["min_timestamp_created"] == "2026-10-31T11:55:00.000Z"      # watermark minus 48 hours
    assert db.sources["instantly"]["synced_through"] == NOW + timedelta(hours=1) - timedelta(minutes=5)
    assert db.sources["instantly"]["measured_from"] == date(2026, 1, 1)
    assert _replies("2026-11-01") == {"people": 1, "auto_replies": 1, "people_7d": 2}


def test_a_campaign_added_to_the_list_later_is_read_from_the_backfill_start(db, api, monkeypatch):
    api.add(received("em1", "2026-11-01T13:00:00Z"),
            received("old2", "2026-10-01T13:00:00Z", "p9@shop.example", campaign=CAMPAIGN_2))
    instantly_sync.run(now=NOW)
    again = instantly_sync.run(now=NOW + timedelta(hours=1))
    assert again["detail"]["from_backfill"] is False
    assert api.params()["min_timestamp_created"] == "2026-10-31T11:55:00.000Z"
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", f"{CAMPAIGN},{CAMPAIGN_2}")
    out = instantly_sync.run(now=NOW + timedelta(hours=2))
    assert out["status"] == "ok" and out["detail"]["from_backfill"] is True
    assert [api.params(i)["min_timestamp_created"] for i in (-2, -1)] == [BACKFILL, BACKFILL]
    assert set(_rows(db)) == {"em1", "old2"}                                  # its October reply too
    src = db.sources["instantly"]
    assert src["account_ref"] == f"campaigns:{CAMPAIGN},{CAMPAIGN_2}" and src["measured_from"] == date(2026, 1, 1)
    assert _replies("2026-10-01")["people"] == 1
    assert instantly_sync.run(now=NOW + timedelta(hours=3))["detail"]["from_backfill"] is False
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", f"{CAMPAIGN_2.upper()}, {CAMPAIGN}")    # the same list
    assert instantly_sync.run(now=NOW + timedelta(hours=4))["detail"]["from_backfill"] is False


def test_a_failed_full_read_is_tried_again_from_the_backfill_start(db, api, monkeypatch):
    instantly_sync.run(now=NOW)
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", f"{CAMPAIGN_2}")
    api.fail_next = [403]
    assert instantly_sync.run(now=NOW + timedelta(hours=1))["status"] == "failed"
    assert db.sources["instantly"]["account_ref"] == f"campaigns:{CAMPAIGN}"     # unchanged: not read yet
    out = instantly_sync.run(now=NOW + timedelta(hours=2))
    assert (out["status"], out["detail"]["from_backfill"]) == ("ok", True)
    assert api.params()["min_timestamp_created"] == BACKFILL
    assert db.sources["instantly"]["account_ref"] == f"campaigns:{CAMPAIGN_2}"


def test_the_watermark_never_moves_back(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    instantly_sync.run(now=NOW + timedelta(hours=2))
    assert instantly_sync.run(now=NOW)["status"] == "ok"               # an earlier run that finishes later
    assert db.sources["instantly"]["synced_through"] == NOW + timedelta(hours=2) - timedelta(minutes=5)


def test_days_widens_the_window_but_never_narrows_it(db, api):
    _synced(db, "2026-11-02T06:00:00Z")
    instantly_sync.run(now=NOW, days=7)
    assert api.params()["min_timestamp_created"] == "2026-10-26T12:00:00.000Z"
    instantly_sync.run(now=NOW + timedelta(hours=1), days=1)
    assert api.params()["min_timestamp_created"] == "2026-10-31T11:55:00.000Z"     # the overlap reaches further


def test_the_first_run_follows_backfill_from(db, api, monkeypatch):
    monkeypatch.setenv("BOARD_BACKFILL_FROM", "2026-10-01")
    api.add(received("old", "2026-09-30T12:00:00Z"), received("em1", "2026-10-15T12:00:00Z"))
    instantly_sync.run(now=NOW)
    assert api.params()["min_timestamp_created"] == "2026-10-01T04:00:00.000Z"       # midnight EDT
    assert set(_rows(db)) == {"em1"} and db.sources["instantly"]["measured_from"] == date(2026, 10, 1)


def test_a_day_before_measured_from_or_past_the_watermark_is_not_final(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    instantly_sync.run(now=datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc))
    day = ledger.board_day(date(2026, 11, 1))
    assert {s["id"]: s["state"] for s in day["sources"]}["instantly"] == "partial"
    assert day["replies"]["people"] == 1
    db.set_source("instantly", measured_from="2026-11-02")
    assert {s["id"]: s["state"] for s in ledger.board_day(date(2026, 11, 1))["sources"]}["instantly"] == \
        "not_connected"


# ─── settings: not configured is a skip ─────────────────────────────────────

@pytest.mark.parametrize("key, campaigns, reason", [
    (None, CAMPAIGN, "no Instantly key: set INSTANTLY_API_KEY (a key with the emails:read scope)"),
    ("   ", CAMPAIGN, "no Instantly key: set INSTANTLY_API_KEY (a key with the emails:read scope)"),
    ("short", CAMPAIGN, "INSTANTLY_API_KEY is not a usable Instantly API key"),
    (KEY[:20] + " " + KEY[20:], CAMPAIGN, "INSTANTLY_API_KEY is not a usable Instantly API key"),
    (KEY, None, NO_CAMPAIGNS),
    (KEY, " , ", NO_CAMPAIGNS),
    (KEY, f"{CAMPAIGN},{KEY}", "BOARD_SITEBOOST_CAMPAIGN_IDS: entry 2 is not an Instantly campaign id"),
    (KEY, "SiteBoost Outbound (auto)", "BOARD_SITEBOOST_CAMPAIGN_IDS: entry 1 is not an Instantly campaign id"),
])
def test_not_configured_is_a_skip_with_no_claim_and_no_call(db, api, monkeypatch, key, campaigns, reason):
    for name, value in (("INSTANTLY_API_KEY", key), ("BOARD_SITEBOOST_CAMPAIGN_IDS", campaigns)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    assert instantly_sync.configured() == reason
    out = instantly_sync.run(now=NOW)
    assert (out["status"], out["error"], out["id"]) == ("skipped", reason, None)
    assert KEY not in out["error"] and KEY[:20] not in out["error"]
    assert db.calls == [] and api.calls == []                         # no claim, no read: the board reads "not connected"


def test_the_active_campaign_file_is_never_a_fallback(db, api, monkeypatch, tmp_path):
    active = tmp_path / "active_campaign.json"
    active.write_text(json.dumps({"id": CAMPAIGN}))
    monkeypatch.setattr(si, "ACTIVE_PATH", active)
    monkeypatch.setenv("INSTANTLY_CAMPAIGN_ID", CAMPAIGN)
    monkeypatch.delenv("BOARD_SITEBOOST_CAMPAIGN_IDS")
    assert si.get_active_campaign_id() == CAMPAIGN                     # the send path keeps its behaviour
    assert instantly_sync.run(now=NOW)["status"] == "skipped" and api.calls == []


def test_campaign_ids_are_lower_cased_in_order_and_listed_once(monkeypatch):
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", f" {CAMPAIGN.upper()} ,\n{CAMPAIGN_2};{CAMPAIGN},")
    assert instantly_sync.campaign_ids() == [CAMPAIGN, CAMPAIGN_2]
    monkeypatch.setenv("INSTANTLY_API_KEY", KEY)
    assert instantly_sync.configured() is None


# ─── limits and failures ────────────────────────────────────────────────────

def test_the_pacer_keeps_calls_3_5_seconds_apart_and_under_instantlys_limit(db, api, monkeypatch):
    monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", f"{CAMPAIGN},{CAMPAIGN_2}")
    api.page_size = 1
    api.add(*[received(f"em{i:02d}", f"2026-11-01T{i:02d}:00:00Z", f"p{i}@shop.example") for i in range(24)])
    api.add(received("other1", "2026-11-01T13:30:00Z", campaign=CAMPAIGN_2))
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "ok" and len(_rows(db)) == 25
    assert len(api.calls) == 25                                          # 24 pages, then the second campaign
    gaps = [b - a for a, b in zip(api.call_times, api.call_times[1:])]
    assert min(gaps) >= si.EMAILS_EVERY
    assert max(sum(1 for t in api.call_times if s <= t < s + 60) for s in api.call_times) <= 20


def test_a_rate_limit_waits_for_retry_after_then_succeeds(db, api, clock):
    api.fail_next = [(429, {"Retry-After": "7"})]
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "ok" and set(_rows(db)) == {"em1"}
    assert len(api.calls) == 2 and api.call_times[1] - api.call_times[0] == 7.0
    assert 7.0 in clock.slept


@pytest.mark.parametrize("headers, wait", [({"Retry-After": "600"}, 30.0), ({}, 15.0),
                                           ({"Retry-After": "soon"}, 15.0), ({"Retry-After": "0"}, 1.0)])
def test_a_rate_limit_wait_is_short_and_capped_at_30_seconds(db, api, clock, headers, wait):
    api.fail_next = [(429, headers)]
    assert instantly_sync.run(now=NOW)["status"] == "ok"
    assert clock.slept[0] == wait


def test_a_rate_limit_that_persists_fails_the_run_and_keeps_the_watermark(db, api, clock):
    _synced(db)
    api.fail_next = [(429, {"Retry-After": "5"})] * 4
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    out = instantly_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "failed"
    assert out["error"] == "Instantly kept limiting the reply list (HTTP 429); the next run tries again"
    assert len(api.calls) == 4 and clock.slept.count(5.0) == 3      # 3 waits, then it gives up
    assert db.sources["instantly"]["synced_through"] == WATERMARK and _rows(db) == {}
    assert db.sources["instantly"]["last_error"] == out["error"]
    (run,) = db.runs("instantly_sync")
    assert run["status"] == "failed" and run["error"] == out["error"] and run["finished_at"] is not None


def test_a_server_error_or_a_timeout_is_retried_after_2_and_4_seconds(db, api, clock):
    api.fail_next = [503, requests.exceptions.ReadTimeout("read timed out")]
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    assert instantly_sync.run(now=NOW)["status"] == "ok" and set(_rows(db)) == {"em1"}
    assert clock.slept == [2.0, 1.5, 4.0]          # 2 s, the pacer's last 1.5 of its 3.5 s, then 4 s


def test_a_lasting_outage_fails_with_a_plain_message_and_no_url(db, api, clock):
    leaky = requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool(host='api.instantly.ai'): Max retries exceeded with url: "
        f"/api/v2/emails?campaign_id={CAMPAIGN}&api_key={KEY}")
    api.fail_next = [502, 503, 504, leaky]
    out = instantly_sync.run(now=NOW)
    assert out["error"] == "Instantly unreachable (ConnectionError); the next run tries again"
    assert [s for s in clock.slept if s in (2.0, 4.0, 8.0)] == [2.0, 4.0, 8.0]
    for text in (out["error"], db.sources["instantly"]["last_error"], db.runs("instantly_sync")[0]["error"]):
        assert KEY not in text and "api.instantly.ai" not in text and "?" not in text


def test_a_refused_key_is_recorded_without_the_key(db, api, caplog):
    caplog.set_level(logging.DEBUG)
    _synced(db)
    api.key = "a-different-key-0000000000"                  # Instantly does not know ours; its answer quotes it
    out = instantly_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "failed"
    assert out["error"] == "Instantly refused the API key (HTTP 401): check INSTANTLY_API_KEY"
    src = db.sources["instantly"]
    assert src["last_error"] == out["error"] and src["synced_through"] == WATERMARK
    (run,) = db.runs("instantly_sync")
    assert run["status"] == "failed" and _rows(db) == {}
    for text in (out["error"], src["last_error"], run["error"], json.dumps(run["detail"]), json.dumps(out),
                 caplog.text):
        assert KEY not in text and KEY[:16] not in text
    assert len(api.calls) == 1                                         # a refusal is not retried


@pytest.mark.parametrize("status, error", [
    (402, "Instantly refused the request (HTTP 402): the plan may not include API access"),
    (403, "Instantly refused the request (HTTP 403): the API key needs the emails:read scope"),
    (404, f"Instantly does not know campaign {CAMPAIGN[:8]} (HTTP 404)"),
    (400, "Instantly answered the reply list with HTTP 400"),
])
def test_a_refusal_says_why_in_plain_words_and_never_writes_a_zero(db, api, status, error):
    api.fail_next = [status]
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    out = instantly_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("failed", error) and len(api.calls) == 1
    src = db.sources["instantly"]
    assert src["last_error"] == error and src["measured_from"] is None and src["synced_through"] is None
    day = ledger.board_day(date(2026, 11, 1))
    assert {s["id"]: s["state"] for s in day["sources"]}["instantly"] == "not_connected"   # null on the board, not 0


def test_an_answer_without_a_list_of_emails_fails_the_run(db, api, monkeypatch):
    monkeypatch.setattr(api, "handle", lambda request, timeout: _answer(request, 200, {"data": []}))
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"] == "Instantly answered the reply list without a list of emails"


def test_emails_without_an_id_or_a_time_are_skipped_and_reported(db, api):
    no_time = received("em2", "2026-11-01T14:00:00Z")
    no_time.update(timestamp_created=None, timestamp_email="not a time")
    unstored = received("em3", "2026-11-01T14:30:00Z")
    unstored.update(timestamp_created=None)                       # sent, but not when Instantly stored it
    api.add(received("em1", "2026-11-01T13:00:00Z"), no_time, unstored,
            {**received("x", "2026-11-01T15:00:00Z"), "id": None})
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "ok" and set(_rows(db)) == {"em1"}
    assert (out["detail"]["no_id"], out["detail"]["no_time"], out["detail"]["undated"]) == (1, 2, 2)
    warning = "skipped 3 emails that Instantly listed without an id or a time: replies may be missing"
    assert out["error"] == warning
    src = db.sources["instantly"]
    assert src["last_error"] == warning and src["last_error_at"] == src["last_ok_at"]   # a warning, not a failure


def test_the_connector_only_reads(db, api):
    api.page_size = 1
    api.fail_next = [429, 500]
    api.add(*[received(f"em{i}", f"2026-11-01T1{i}:00:00Z", f"p{i}@shop.example") for i in range(3)])
    assert instantly_sync.run(now=NOW)["status"] == "ok"
    assert {(c.method, urlsplit(c.url).path) for c in api.calls} == {("GET", "/api/v2/emails")}
    assert set().union(*(api.params(i) for i in range(len(api.calls)))) <= ALLOWED_PARAMS


def test_one_run_at_a_time_and_no_read_while_busy(db, api):
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    db._rpc_board_claim_run("instantly_sync", "an-earlier-run", "schedule", "instantly")
    out = instantly_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("busy", "another Instantly sync is running") and api.calls == []


def test_the_database_down_fails_the_run_without_calling_instantly(db, api):
    db.down = True
    out = instantly_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"].startswith("database:") and api.calls == []


def test_a_disabled_source_is_skipped_without_a_read(db, api):
    db.set_source("instantly", enabled=False)
    out = instantly_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("skipped", "the instantly source is disabled") and api.calls == []
    assert db.runs("instantly_sync")[0]["status"] == "skipped"


def test_a_database_refusal_keeps_the_watermark(db, api):
    _synced(db)
    db.fail["rpc/board_ingest_leads"] = 500
    api.add(received("em1", "2026-11-01T13:00:00Z"))
    out = instantly_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "failed" and "board_ingest_leads" in out["error"] and "@" not in out["error"]
    assert db.sources["instantly"]["synced_through"] == WATERMARK


# ─── list_replies itself ────────────────────────────────────────────────────

def test_list_replies_returns_plain_fields_and_keeps_its_counts(api):
    api.add(received("em1", "2026-11-01T13:00:00Z", "P1@Shop.example", auto=None, i_status=None))
    stats: dict = {}
    (reply,) = si.list_replies(CAMPAIGN.upper(), NOW - timedelta(days=3), NOW, stats=stats)
    assert reply == {"id": "em1", "campaign_id": CAMPAIGN, "lead": "p1@shop.example",
                     "lead_id": _uuid("lead:P1@Shop.example"), "from_address": "p1@shop.example",
                     "to_addresses": (OURS,), "eaccount": OURS, "subject": "Re: Jay — quick fix idea for Shop Co",
                     "timestamp_created": datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc),
                     "timestamp_email": datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc),
                     "message_id": "<em1.reply@mx.shop.example>", "thread_id": _uuid("thread:P1@Shop.example"),
                     "ue_type": 2, "i_status": None, "is_auto_reply": None}
    assert "body" not in reply and "content_preview" not in reply
    assert stats == {"pages": 1, "listed": 1, "kept": 1, "sent_by_us": 0, "other_campaign": 0,
                     "outside_window": 0, "undated": 0, "no_id": 0, "duplicates": 0}


def test_list_replies_refuses_a_bad_campaign_or_a_naive_time_before_any_call(api):
    for bad in ("SiteBoost", "", None, CAMPAIGN + "0"):
        with pytest.raises(ValueError):
            si.list_replies(bad, NOW - timedelta(days=1), NOW)
    with pytest.raises(ValueError):
        si.list_replies(CAMPAIGN, datetime(2026, 11, 1), NOW)
    assert api.calls == []


def test_list_replies_without_a_key_raises_a_plain_error(api, monkeypatch):
    monkeypatch.delenv("INSTANTLY_API_KEY")
    with pytest.raises(si.InstantlyError, match="INSTANTLY_API_KEY is not set or not usable"):
        si.list_replies(CAMPAIGN, NOW - timedelta(days=1), NOW)
    assert api.calls == []


def test_the_flags_and_codes_are_read_defensively():
    assert [si._flag(v) for v in (1, 0, True, False, "1", "0", None, 2, "yes", 0.0)] == \
        [True, False, True, False, True, False, None, None, None, False]
    assert [si._code(v) for v in (2, 0, -1, 3.0, 2.5, "2", True, None)] == [2, 0, -1, 3, None, None, None, None]
    assert si._when("2026-11-01T13:00:00.000Z") == datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
    assert si._when("2026-11-01T09:00:00-04:00") == datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
    assert si._when("2026-11-01T13:00:00") == datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
    assert [si._when(v) for v in ("yesterday", "", None, 1730000000)] == [None, None, None, None]
    assert si._addresses("a@x.example, Pat <B@Y.example>,junk") == ("a@x.example", "b@y.example")
