"""The Meta connector (core/board/connectors/meta_sync.py) and the Meta
client's reads (core/meta_ads.py: account_info, daily_insights). Meta spend
feeds the stop rule, so its verdicts are checked here end to end: Meta's
answer, the sync, the upsert, then board_day. No network: graph.facebook.com
is a requests adapter mounted on the client's session (FakeGraph, below), and
Supabase is tests/board_fakes.py."""
import base64
import hashlib
import hmac
import itertools
import json
import logging
import traceback
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from core import meta_ads
from core.board import day as board_day
from core.board import ledger
from core.board.connectors import meta_sync
from core.meta_ads import MetaAdsClient, MetaAdsError
from tests import board_fakes as bf

TOKEN = "FAKEMETAboardInsights0a1b2c3d4e5f6g7h8i9j0kLMNOPqrstu"      # fake
APP_SECRET = "fakeappsecret0123456789abcdef0000"                    # fake
ACCOUNT = "1234567890"
TOODLE = bf.TOODLE_CAMPAIGN
OTHER = "120000000000000001"
LA = "America/Los_Angeles"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)      # 07:00 in New York, 04:00 in Los Angeles
ENV = ("META_INSIGHTS_TOKEN", "META_ACCESS_TOKEN", "AD_ACCOUNT_ID", "FB_AD_ACCOUNT_ID", "PAGE_ID",
       "FACEBOOK_PAGE_ID", "BOARD_TOODLE_META_CAMPAIGN_IDS", "META_GRAPH_VERSION", "META_APP_SECRET")


# ─── a fake graph.facebook.com ──────────────────────────────────────────────

def _response(request, status: int, body, headers=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body).encode()
    r.headers = CaseInsensitiveDict({"Content-Type": "application/json; charset=UTF-8", **(headers or {})})
    r.encoding = "utf-8"
    r.url = request.url
    r.request = request
    r.reason = "OK" if status == 200 else "Bad Request"
    return r


def _cursor(offset: int) -> str:
    return base64.b64encode(f"offset:{offset}".encode()).decode()


def _proof(secret: str, token: str = TOKEN) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def _refused(request):
    """What requests raises when nobody answers: its text holds the path and
    the query string, the token too when it rides in the URL."""
    return requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries exceeded with url: "
        f"{request.path_url} (Caused by NewConnectionError('Failed to establish a new connection'))")


def throttle(code: int = 80000, subcode: int = 2446079):
    """One rate-limit refusal, with Meta's usage header."""
    usage = {ACCOUNT: [{"type": "ads_insights", "call_count": 100, "total_cputime": 20, "total_time": 30,
                        "estimated_time_to_regain_access": 5, "ads_api_access_tier": "standard_access"}]}
    return (400, {"message": "There have been too many calls from this ad-account. Wait a bit and try again.",
                  "type": "OAuthException", "code": code, "error_subcode": subcode, "is_transient": True,
                  "fbtrace_id": "ThrottleTrace01"}, {"X-Business-Use-Case-Usage": json.dumps(usage)})


class FakeGraph(BaseAdapter):
    """graph.facebook.com for one ad account, as Meta answers it: GET
    /{version}/act_{id} and GET /{version}/act_{id}/insights, whose pages
    carry a cursor every time and a `next` link only while more follow,
    written with whatever the request carried (the token too, when it came
    as a parameter). Errors are Meta's {"error": {...}} with status 400. The
    token is read from the Authorization header, or from access_token when
    header_auth is False; a wrong one is refused with code 190, echoed."""

    def __init__(self):
        super().__init__()
        self.token = TOKEN
        self.account = ACCOUNT
        self.app_secret = APP_SECRET           # the secret of the app that made the token
        self.require_proof = False             # the app's "Require App Secret"
        self.header_auth = True
        self.info = {"id": f"act_{ACCOUNT}", "account_id": ACCOUNT, "name": "Toodle ads", "currency": "USD",
                     "timezone_name": LA, "account_status": 1}
        self.rows: dict[tuple[str, str], dict] = {}
        self.calls: list[requests.PreparedRequest] = []
        self.fail_next: list[tuple] = []       # (status, error, headers) answered first, after sign-in
        self.raise_next: list = []             # functions of the request: the exception to raise first
        self.page_size = None                  # None: the request's own limit
        self.served_version = None             # facebook-api-version; None: the version asked for
        self.extra_headers: dict = {}
        self.too_much_over = None              # a range of more days than this times out (100/1504018)
        self.sleeps: list[float] = []

    def add(self, day: str, spend, campaign: str = TOODLE, *, name="Toodle opt-in", impressions="1200",
            clicks="9", actions=None, currency="USD", **fields) -> "FakeGraph":
        """One campaign-day as Meta lists it; a field given as None is left out."""
        row = {"campaign_id": campaign, "campaign_name": name, "spend": spend, "impressions": impressions,
               "inline_link_clicks": clicks, "actions": actions, "account_currency": currency,
               "date_start": day, "date_stop": day, **fields}
        self.rows[(campaign, day)] = {k: v for k, v in row.items() if v is not None}
        return self

    def insights_calls(self) -> list:
        return [c for c in self.calls if urlsplit(c.url).path.endswith("/insights")]

    def ranges(self) -> list[tuple[str, str]]:
        """The date ranges read, in order: one per first page."""
        out = []
        for c in self.insights_calls():
            q = parse_qs(urlsplit(c.url).query)
            window = json.loads(q["time_range"][0])
            if "after" not in q and (not out or out[-1] != (window["since"], window["until"])):
                out.append((window["since"], window["until"]))
        return out

    # ── requests' adapter ──
    def close(self):
        pass

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.calls.append(request)
        assert timeout and timeout > 0        # never an endless wait; the owner's route answers within 50 s
        if self.raise_next:
            raise self.raise_next.pop(0)(request)
        url = urlsplit(request.url)
        q = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        version, _, path = url.path.lstrip("/").partition("/")
        bearer = request.headers.get("Authorization", "")
        token = bearer[len("Bearer "):] if (self.header_auth and bearer.startswith("Bearer ")) \
            else q.get("access_token")
        if not token:
            return self._error(request, 2500, "An active access token must be used to query information "
                                              "about the current user.", "OAuthException")
        if token != self.token:
            return self._error(request, 190, f"Error validating access token: the token {token} has expired.",
                               "OAuthException", subcode=463)
        proof = q.get("appsecret_proof")
        if proof is not None and proof != _proof(self.app_secret, token):
            return self._error(request, 100, "Invalid appsecret_proof provided in the API argument",
                               "GraphMethodException")
        if proof is None and self.require_proof:
            return self._error(request, 100, "API calls from the server require an appsecret_proof argument",
                               "GraphMethodException")
        if self.fail_next:
            status, error, headers = self.fail_next.pop(0)
            return _response(request, status, {"error": error}, headers)
        if path == f"act_{self.account}":
            fields = q.get("fields", "").split(",")
            return self._ok(request, version, {k: v for k, v in self.info.items() if k in fields and v is not None})
        if path == f"act_{self.account}/insights":
            return self._insights(request, version, path, q)
        if path.startswith("act_"):
            return self._error(request, 100, "Unsupported get request. Object with ID 'act_x' does not exist",
                               "GraphMethodException", subcode=33)
        return self._ok(request, version, {"id": path, "status": "PAUSED"})       # any other node

    def _ok(self, request, version, body):
        headers = {"facebook-api-version": self.served_version or version, **self.extra_headers}
        return _response(request, 200, body, headers)

    def _error(self, request, code, message, kind, subcode=None, transient=False):
        error = {"message": message, "type": kind, "code": code, "is_transient": transient,
                 "fbtrace_id": "AbCdEf12_trace"}
        if subcode is not None:
            error["error_subcode"] = subcode
        return _response(request, 400, {"error": error})

    def _insights(self, request, version, path, q):
        for banned in ("filtering", "action_report_time", "use_unified_attribution_setting",
                       "action_attribution_windows", "date_preset", "breakdowns"):
            assert banned not in q, banned
        assert (q["level"], q["time_increment"]) == ("campaign", "1")
        assert set(q["fields"].split(",")) >= {"campaign_id", "campaign_name", "spend", "impressions",
                                               "inline_link_clicks", "actions", "date_start", "date_stop"}
        window = json.loads(q["time_range"])
        assert q["time_range"] == json.dumps(window, sort_keys=True, separators=(",", ":"))
        since, until = window["since"], window["until"]
        days = (date.fromisoformat(until) - date.fromisoformat(since)).days + 1
        if self.too_much_over is not None and days > self.too_much_over:
            return self._error(request, 100, "Request Timed Out", "OAuthException", subcode=1504018)
        rows = [self.rows[k] for k in sorted(self.rows, key=lambda k: (k[1], k[0])) if since <= k[1] <= until]
        size = self.page_size or int(q.get("limit", "25"))
        start = int(base64.b64decode(q["after"]).decode().split(":")[1]) if "after" in q else 0
        page = rows[start:start + size]
        body = {"data": [dict(r) for r in page],
                "paging": {"cursors": {"before": _cursor(start), "after": _cursor(start + len(page))}}}
        if start + size < len(rows):
            body["paging"]["next"] = (f"https://graph.facebook.com/{version}/{path}?"
                                      + urlencode({**q, "after": _cursor(start + size)}))
        return self._ok(request, version, body)


def _days(first: str, n: int) -> list[str]:
    start = date.fromisoformat(first)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


@pytest.fixture
def db(monkeypatch):
    return bf.install_board(monkeypatch)


@pytest.fixture
def graph(monkeypatch):
    """A fresh FakeGraph behind core.meta_ads, the Meta settings for these
    tests, and no real waiting."""
    fake = FakeGraph()
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("META_INSIGHTS_TOKEN", TOKEN)
    monkeypatch.setenv("AD_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TOODLE)
    monkeypatch.setattr(meta_ads, "_adapter", fake)
    monkeypatch.setattr(meta_ads, "_sleep", fake.sleeps.append)
    return fake


def _client(**kw) -> MetaAdsClient:
    return MetaAdsClient(access_token=TOKEN, ad_account_id=ACCOUNT, **kw)


def _query(request) -> dict:
    return parse_qs(urlsplit(request.url).query)


# ─── the client's reads (core/meta_ads.py) ──────────────────────────────────

def test_reads_need_a_token_and_an_ad_account_but_no_page(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    client = MetaAdsClient(access_token=TOKEN, ad_account_id=f"act_{ACCOUNT}")
    assert client.is_read_configured() and not client.is_configured()        # creating ads still needs a Page
    assert client.acct == f"act_{ACCOUNT}"
    assert MetaAdsClient(access_token=TOKEN, ad_account_id=ACCOUNT, page_id="42").is_configured()
    without_account = MetaAdsClient(access_token=TOKEN)
    assert not without_account.is_read_configured()
    with pytest.raises(MetaAdsError):
        without_account.account_info()                                        # refused before any call


def test_the_default_graph_version_is_one_meta_still_serves_for_ads(monkeypatch):
    monkeypatch.delenv("META_GRAPH_VERSION", raising=False)
    assert meta_ads.DEFAULT_VERSION == "v26.0" and MetaAdsClient().version == "v26.0"
    monkeypatch.setenv("META_GRAPH_VERSION", "v25.0")
    assert MetaAdsClient().version == "v25.0"


def test_account_info_sends_the_token_in_a_header_never_in_the_url(graph):
    info = _client().account_info()
    assert info == {"id": f"act_{ACCOUNT}", "account_id": ACCOUNT, "name": "Toodle ads", "currency": "USD",
                    "timezone_name": LA, "account_status": 1}
    (call,) = graph.calls
    assert call.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in call.url and "access_token" not in call.url and "appsecret_proof" not in call.url
    assert urlsplit(call.url).path == f"/v26.0/act_{ACCOUNT}"
    assert _query(call) == {"fields": ["id,account_id,name,currency,timezone_name,account_status"]}


def test_daily_insights_reads_every_page_by_its_cursor(graph):
    for d in _days("2026-10-27", 7):
        graph.add(d, "5.02").add(d, "10.00", OTHER, name="Brand awareness")
    graph.page_size = 3
    rows = _client().daily_insights(date(2026, 10, 27), "2026-11-02")
    assert len(rows) == 14 and {(r["campaign_id"], r["date_start"]) for r in rows} == set(graph.rows)
    params = [_query(c) for c in graph.calls]
    assert len(params) == 5                                                    # 14 rows, 3 a page
    assert all(p["time_range"] == ['{"since":"2026-10-27","until":"2026-11-02"}'] for p in params)
    assert all((p["level"], p["time_increment"], p["limit"]) == (["campaign"], ["1"], ["200"]) for p in params)
    assert params[0]["fields"] == [",".join(meta_ads.INSIGHTS_FIELDS)]
    # the cursor of each page, never a `next` link (it can carry the token)
    assert "after" not in params[0] and [p["after"][0] for p in params[1:]] == [_cursor(n) for n in (3, 6, 9, 12)]
    assert all(urlsplit(c.url).path == f"/v26.0/act_{ACCOUNT}/insights" for c in graph.calls)


def test_a_range_meta_times_out_on_is_read_in_halves_and_one_day_is_not_split(graph):
    for d in _days("2026-10-03", 31):
        graph.add(d, "1.00")
    graph.too_much_over = 10
    rows = _client().daily_insights("2026-10-03", "2026-11-02")
    assert sorted(r["date_start"] for r in rows) == _days("2026-10-03", 31)
    assert len(graph.insights_calls()) == 7 and graph.sleeps == []        # 31 days, two halves, four quarters
    assert graph.ranges()[-1] == ("2026-10-27", "2026-11-02")
    graph.too_much_over = 0
    with pytest.raises(MetaAdsError) as e:
        _client().daily_insights("2026-11-01", "2026-11-01")
    assert e.value.too_much_data and (e.value.code, e.value.subcode) == (100, 1504018)


def test_get_takes_extra_query_params_but_never_a_token_among_them(graph):
    client = _client()
    assert client.get_node("120330000000000001")["status"] == "PAUSED"
    client._get("120330000000000001", fields="id,status",
                params={"date_preset": "today", "access_token": "x", "appsecret_proof": "y"})
    assert _query(graph.calls[-1]) == {"fields": ["id,status"], "date_preset": ["today"]}
    assert graph.calls[-1].headers["Authorization"] == f"Bearer {TOKEN}"


def test_creating_ads_still_posts_the_token_in_the_form_body(monkeypatch):
    sent = []

    def post(url, data=None, files=None, timeout=None):
        sent.append((url, data, timeout))
        r = requests.Response()
        r.status_code, r._content = 200, b'{"id": "120330000000000009"}'
        return r

    monkeypatch.setattr(meta_ads.requests, "post", post)
    client = MetaAdsClient(access_token=TOKEN, ad_account_id=ACCOUNT, page_id="42", version="v26.0")
    assert client.create_campaign("Toodle test") == "120330000000000009"
    ((url, data, timeout),) = sent
    assert url == f"https://graph.facebook.com/v26.0/act_{ACCOUNT}/campaigns" and timeout == 60
    assert data["access_token"] == TOKEN and data["status"] == "PAUSED"


def test_the_token_goes_as_a_parameter_only_when_meta_does_not_take_the_header(graph, caplog):
    caplog.set_level(logging.DEBUG)
    graph.header_auth = False
    client = _client()
    assert client.account_info()["currency"] == "USD"
    first, second = graph.calls
    assert "access_token" not in first.url and _query(second)["access_token"] == [TOKEN]
    assert client.token_sent_as == "parameter"
    client.account_info()
    assert len(graph.calls) == 3                                               # no second refusal
    assert TOKEN not in caplog.text


def test_appsecret_proof_is_sent_and_dropped_when_meta_says_it_is_another_apps(graph):
    _client(app_secret=APP_SECRET).account_info()
    assert _query(graph.calls[-1])["appsecret_proof"] == [_proof(APP_SECRET)]
    other = _client(app_secret="another-apps-secret-00000000000")
    assert other.account_info()["currency"] == "USD"
    assert other.proof_dropped and "appsecret_proof" not in graph.calls[-1].url
    graph.require_proof = True
    with pytest.raises(MetaAdsError) as e:
        _client().account_info()
    assert e.value.code == 100 and "appsecret_proof" in e.value.meta_message


def test_no_answer_never_carries_the_url_or_the_token(graph, caplog):
    caplog.set_level(logging.DEBUG)
    client = _client(app_secret=APP_SECRET)
    client.token_sent_as = "parameter"                                         # the token rides in the URL here
    graph.raise_next = [_refused] * 4
    with pytest.raises(MetaAdsError) as e:
        client.daily_insights("2026-11-01", "2026-11-02")
    assert e.value.network and e.value.retries == 3 and graph.sleeps == [2.0, 8.0, 30.0]
    assert str(e.value) == f"GET /act_{ACCOUNT}/insights: Meta could not be reached (ConnectionError)"
    told = [str(e.value), repr(e.value.payload), caplog.text, "".join(traceback.format_exception(e.value))]
    assert TOKEN in graph.calls[0].url                                         # it was in the URL ...
    for text in told:                                                          # ... and is nowhere else
        assert TOKEN not in text and _proof(APP_SECRET) not in text and "access_token" not in text


def test_a_refusal_is_structured_and_hides_what_meta_echoes(graph):
    said = f"Error validating access token: the token {TOKEN} has expired; it began {TOKEN[:12]}"
    refusal = (400, {"message": said, "type": "OAuthException", "code": 190, "error_subcode": 463,
                     "fbtrace_id": "AbC123_def-456"}, {"x-app-usage": '{"call_count":5}'})
    graph.fail_next = [refusal, refusal]                                       # the header, then the parameter
    with pytest.raises(MetaAdsError) as e:
        _client().account_info()
    err = e.value
    assert (err.status_code, err.code, err.subcode, err.error_type, err.fbtrace_id, err.retries) == \
        (400, 190, 463, "OAuthException", "AbC123" "_def-456", 0)
    assert err.headers == {"x-app-usage": '{"call_count":5}'} and not err.transient and not err.throttled
    assert err.meta_message == "Error validating access token: the token [hidden] has expired; it began [hidden]"
    assert str(err) == f"GET /act_{ACCOUNT}: HTTP 400, code 190/463: {err.meta_message}"
    assert TOKEN[:12] not in json.dumps(err.payload) and err.payload["error"]["code"] == 190


# ─── configuration ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("env, reason", [
    ({}, "Meta token not set: META_INSIGHTS_TOKEN (or META_ACCESS_TOKEN)"),
    ({"META_INSIGHTS_TOKEN": TOKEN}, "Meta ad account not set: AD_ACCOUNT_ID (or FB_AD_ACCOUNT_ID)"),
    ({"META_INSIGHTS_TOKEN": "has a space", "AD_ACCOUNT_ID": ACCOUNT},
     "META_INSIGHTS_TOKEN holds spaces or other characters a token cannot have"),
    ({"META_ACCESS_TOKEN": TOKEN, "AD_ACCOUNT_ID": "act_12x"},
     "AD_ACCOUNT_ID is not an ad account number (digits, with or without act_)"),
    ({"META_ACCESS_TOKEN": TOKEN, "FB_AD_ACCOUNT_ID": ACCOUNT, "META_GRAPH_VERSION": "26.0"},
     "META_GRAPH_VERSION must look like v26.0"),
])
def test_an_unconfigured_sync_is_skipped_with_no_claim_and_no_call(db, graph, monkeypatch, env, reason):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    out = meta_sync.run(now=NOW)
    assert (out["status"], out["error"], out["id"]) == ("skipped", reason, None)
    assert meta_sync.configured() == reason
    assert db.calls == [] and graph.calls == []


def test_the_settings_are_read_the_way_the_client_reads_them(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("META_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("FB_AD_ACCOUNT_ID", f" act_{ACCOUNT} ")
    assert meta_sync.configured() is None
    assert meta_sync.read_token() == (TOKEN, "META_ACCESS_TOKEN") and meta_sync.ad_account() == ACCOUNT
    monkeypatch.setenv("META_INSIGHTS_TOKEN", "FAKEMETAsystemUser01")
    monkeypatch.setenv("AD_ACCOUNT_ID", "987")
    assert meta_sync.read_token() == ("FAKEMETAsystemUser01", "META_INSIGHTS_TOKEN")
    assert meta_sync.ad_account() == "987" and meta_sync.graph_version() == "v26.0"
    monkeypatch.setenv("META_INSIGHTS_TOKEN", "broken token")                 # never falls back to the ads token
    assert meta_sync.read_token() is None and "META_INSIGHTS_TOKEN holds" in meta_sync.configured()
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f" {TOODLE}, abc ,,120000000000000002,"
                                                         f"{'9' * 40}")
    ids, warnings = meta_sync.toodle_campaigns()
    assert ids == {TOODLE, "120000000000000002"}
    assert warnings == ['BOARD_TOODLE_META_CAMPAIGN_IDS: "abc" is not a campaign id, so it was ignored',
                        "BOARD_TOODLE_META_CAMPAIGN_IDS: a long item is not a campaign id, so it was ignored"]


# ─── a run: the account, the window, the rows ───────────────────────────────

def test_the_first_run_records_the_account_and_reads_90_days(db, graph):
    graph.add("2026-11-01", "5.02", clicks="9")
    graph.add("2026-11-01", "10.00", OTHER, name="Brand awareness", clicks="40", impressions="9000")
    graph.add("2026-08-05", "1.00")                                            # 90 days back, today included: in
    graph.add("2026-08-04", "99.00")                                           # 91: never asked for
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok", out
    src = db.sources["meta_ads"]
    assert (src["day_tz"], src["currency"], src["account_ref"]) == (LA, "USD", f"act_{ACCOUNT}")
    assert src["measured_from"] == date(2026, 8, 5) and src["synced_through"] == NOW
    assert src["last_error"] is None and src["last_ok_at"] is not None
    # 2 Nov in Los Angeles; at most 31 days a call
    assert graph.ranges() == [("2026-08-05", "2026-09-04"), ("2026-09-05", "2026-10-05"),
                              ("2026-10-06", "2026-11-02")]
    rows = db.spend_rows()
    assert set(rows) == {(TOODLE, "2026-11-01"), (OTHER, "2026-11-01"), (TOODLE, "2026-08-05")}
    toodle = rows[(TOODLE, "2026-11-01")]
    assert (toodle["spend_minor"], toodle["spend_usd_cents"], toodle["fx_source"], toodle["currency"]) == \
        (502, 502, "identity", "USD")                                          # a USD account is its own USD
    assert (toodle["funnel"], toodle["link_clicks"], toodle["impressions"], toodle["campaign_name"]) == \
        ("toodle", 9, 1200, "Toodle opt-in")
    assert rows[(OTHER, "2026-11-01")]["funnel"] is None                       # not a Toodle campaign
    (run,) = db.runs("meta_sync")
    assert (run["status"], run["rows_written"], run["error"], run["source_id"]) == ("ok", 3, None, "meta_ads")
    assert run["covered_until"] == NOW and all(r["job_run_id"] == run["id"] for r in rows.values())
    assert run["window_start"] == datetime(2026, 8, 5, 7, 0, tzinfo=timezone.utc)   # midnight PDT
    detail = out["detail"]
    assert detail["days"] == {"since": "2026-08-05", "until": "2026-11-02", "count": 90}
    assert (detail["token"], detail["token_sent_as"], detail["account"], detail["version"]) == \
        ("META_INSIGHTS_TOKEN", "header", f"act_{ACCOUNT}", "v26.0")
    assert (detail["rows"], detail["toodle_rows"], detail["toodle_campaigns_seen"]) == (3, 2, [TOODLE])
    assert db.rpc_calls("board_fill_fx") == []                                 # nothing to convert
    assert all(TOKEN not in c.url for c in graph.calls)


def test_later_runs_read_29_days_and_days_widens_but_never_narrows(db, graph):
    meta_sync.run(now=NOW)
    for later, days, expected in ((6, None, "2026-10-05"), (7, 31, "2026-10-03"), (8, 3, "2026-10-05")):
        graph.calls.clear()
        assert meta_sync.run(now=NOW + timedelta(hours=later), days=days)["status"] == "ok"
        assert graph.ranges() == [(expected, "2026-11-02")]                  # one Insights call
    assert db.sources["meta_ads"]["measured_from"] == date(2026, 8, 5)        # set by the first run only
    assert db.sources["meta_ads"]["synced_through"] == NOW + timedelta(hours=8)


def test_meta_revisions_up_to_28_days_back_are_read_again(db, graph):
    for day in ("2026-10-03", "2026-10-04", "2026-10-05", "2026-10-23", "2026-11-01"):
        graph.add(day, "5.02")
    meta_sync.run(now=NOW)
    for day in ("2026-10-04", "2026-10-05", "2026-10-23"):                   # Meta credits back some spend
        graph.add(day, "4.80")
    meta_sync.run(now=NOW + timedelta(hours=1))                               # still 2 Nov in Los Angeles
    spend = {d: r["spend_minor"] for (_, d), r in db.spend_rows().items()}
    assert spend == {"2026-10-03": 502, "2026-10-04": 502, "2026-10-05": 480, "2026-10-23": 480,
                     "2026-11-01": 502}                                       # 28 days back and nearer: read again
    assert ledger.board_day(date(2026, 10, 23))["spend"]["toodle_usd_cents"] == 480


def test_a_run_after_a_gap_reads_every_day_since_the_last_one(db, graph):
    db.set_source("meta_ads", measured_from="2026-08-01", synced_through="2026-09-20T15:00:00Z")
    assert meta_sync.run(now=NOW)["status"] == "ok"
    assert graph.ranges() == [("2026-09-20", "2026-10-20"), ("2026-10-21", "2026-11-02")]   # 08:00 on 20 Sep in LA


def test_an_evening_run_reads_the_ad_accounts_own_today(db, graph):
    # 03:30Z on Mon 2 Nov is 19:30 on Sun 1 Nov in Los Angeles: the account's today is 1 Nov, so the run
    # reads 4 Oct to 1 Nov, and never asks Meta for a day that has not begun for the account.
    db.set_source("meta_ads", measured_from="2026-08-05", synced_through="2026-11-01T20:00:00Z",
                  account_ref=f"act_{ACCOUNT}", day_tz=LA)
    out = meta_sync.run(now=datetime(2026, 11, 2, 3, 30, tzinfo=timezone.utc))
    assert out["status"] == "ok", out
    assert graph.ranges() == [("2026-10-04", "2026-11-01")]
    assert out["detail"]["days"] == {"since": "2026-10-04", "until": "2026-11-01", "count": 29}


def test_a_run_after_a_gap_reads_again_the_account_day_the_last_run_started_on(db, graph):
    # The last complete run started at 03:00Z on Sun 20 Sep, 20:00 on Sat 19 Sep in Los Angeles, so it
    # read 19 Sep only to that evening. The next run, after a gap, starts at the account's 19 Sep, not
    # UTC's 20 Sep: otherwise 19 Sep keeps the evening's spend missing and still reads final.
    db.set_source("meta_ads", measured_from="2026-08-05", synced_through="2026-09-20T03:00:00Z",
                  account_ref=f"act_{ACCOUNT}", day_tz=LA)
    ledger.upsert_ad_spend("meta_ads", None, [bf.spend("2026-09-19", 300)])     # what that run saw
    graph.add("2026-09-19", "5.00")                                              # the whole day, as Meta has it now
    assert meta_sync.run(now=NOW)["status"] == "ok"
    assert graph.ranges() == [("2026-09-19", "2026-10-19"), ("2026-10-20", "2026-11-02")]
    day = ledger.board_day(date(2026, 9, 19))
    assert day["spend"]["toodle_usd_cents"] == 500
    assert {s["id"]: s["state"] for s in day["sources"]}["meta_ads"] == "final"


def test_a_new_ad_account_is_read_like_a_first_run_and_named(db, graph):
    db.set_source("meta_ads", measured_from="2026-08-01", synced_through="2026-11-02T06:00:00Z",
                  account_ref="act_999")
    graph.add("2026-11-01", "5.02")
    out = meta_sync.run(now=NOW)
    assert graph.ranges()[0] == ("2026-08-05", "2026-09-04")
    assert out["error"] == f"the ad account changed from act_999 to act_{ACCOUNT}, so its last 90 days were read"
    assert db.sources["meta_ads"]["account_ref"] == f"act_{ACCOUNT}"
    assert db.sources["meta_ads"]["measured_from"] == date(2026, 8, 1)


def test_a_new_account_whose_first_read_fails_is_read_whole_next_time(db, graph):
    db.set_source("meta_ads", measured_from="2026-08-01", synced_through="2026-11-02T06:00:00Z",
                  account_ref="act_999", day_tz="America/New_York")
    graph.too_much_over = 0                                                    # every Insights read times out
    assert meta_sync.run(now=NOW)["status"] == "failed"
    src = db.sources["meta_ads"]
    assert (src["account_ref"], src["day_tz"]) == ("act_999", "America/New_York")   # nothing recorded yet
    graph.too_much_over, graph.calls = None, []
    out = meta_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok" and graph.ranges()[0] == ("2026-08-05", "2026-09-04")
    assert (db.sources["meta_ads"]["account_ref"], db.sources["meta_ads"]["day_tz"]) == (f"act_{ACCOUNT}", LA)


def test_the_sync_follows_every_page(db, graph):
    for d in _days("2026-10-27", 7):
        graph.add(d, "5.02").add(d, "1.00", OTHER)
    graph.page_size = 4
    db.set_source("meta_ads", measured_from="2026-08-05", synced_through="2026-11-02T06:00:00Z")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and out["rows_written"] == 14 and len(db.spend_rows()) == 14
    assert len(graph.insights_calls()) == 4                                    # 14 rows, 4 a page


def test_spend_is_read_as_a_decimal_into_minor_units(db, graph):
    graph.add("2026-11-01", "12.34").add("2026-11-02", "0.07", OTHER).add("2026-10-31", "4.875", "120000000000000003")
    out = meta_sync.run(now=NOW)
    rows = db.spend_rows()
    assert rows[(TOODLE, "2026-11-01")]["spend_minor"] == 1234
    assert rows[(OTHER, "2026-11-02")]["spend_minor"] == 7
    assert rows[("120000000000000003", "2026-10-31")]["spend_minor"] == 488    # rounded half up, and counted
    assert out["detail"]["rounded_spend"] == 1
    assert meta_sync.spend_minor("1500", "JPY", "x") == (1500, False)
    assert meta_sync.spend_minor("1500.00", "JPY", "x") == (1500, False)
    assert meta_sync.spend_minor("1.234", "KWD", "x") == (1234, False)
    assert meta_sync.spend_minor(None, "USD", "x") == (0, False)               # Meta left it out: none spent


def test_an_amount_with_more_decimals_than_its_currency_is_rounded_in_that_currency(db, graph):
    # yen have no minor unit and dinars have three: the rounding is in the currency's own unit, not cents
    assert meta_sync.spend_minor("1500.5", "JPY", "x") == (1501, True)
    assert meta_sync.spend_minor("1.2345", "KWD", "x") == (1235, True)
    graph.info.update(currency="JPY", timezone_name="Asia/Tokyo")
    graph.add("2026-11-02", "1500.5", currency="JPY")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["rounded_spend"] == 1
    assert db.spend_rows()[(TOODLE, "2026-11-02")]["spend_minor"] == 1501       # ¥1,501, never ¥150,050


def test_a_yen_account_has_no_minor_unit_and_waits_for_a_rate(db, graph):
    graph.info.update(currency="JPY", timezone_name="Asia/Tokyo")
    graph.add("2026-11-02", "1500", currency="JPY")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok"
    row = db.spend_rows()[(TOODLE, "2026-11-02")]
    assert (row["spend_minor"], row["currency"], row["spend_usd_cents"], row["fx_source"]) == (1500, "JPY", None, None)
    assert db.sources["meta_ads"]["day_tz"] == "Asia/Tokyo"
    assert graph.ranges()[-1][1] == "2026-11-02"                               # 21:00 on 2 Nov in Tokyo


def test_a_euro_accounts_spend_has_no_usd_until_a_rate_exists(db, graph):
    graph.info.update(currency="EUR", timezone_name="Europe/Berlin")
    graph.add("2026-11-01", "4.50", currency="EUR")
    out = meta_sync.run(now=NOW)
    row = db.spend_rows()[(TOODLE, "2026-11-01")]
    assert (row["spend_minor"], row["currency"], row["spend_usd_cents"], row["fx_source"]) == (450, "EUR", None, None)
    assert out["detail"]["fx_converted"] == 0 and len(db.rpc_calls("board_fill_fx")) == 1
    db.add_fx_rate("EUR", "2026-10-30", "1.1")                                 # Friday's ECB rate, for Sunday
    out = meta_sync.run(now=NOW + timedelta(hours=1))
    row = db.spend_rows()[(TOODLE, "2026-11-01")]
    assert (row["spend_usd_cents"], row["fx_source"], out["detail"]["fx_converted"]) == (495, "ecb", 1)


def test_toodle_spend_is_the_listed_campaigns_only(db, graph, monkeypatch):
    second = "120249191226470280"
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{TOODLE}, {second}")
    graph.add("2026-11-01", "5.02").add("2026-11-01", "2.00", second).add("2026-11-01", "10.00", OTHER)
    meta_sync.run(now=NOW)
    funnels = {cid: r["funnel"] for (cid, _), r in db.spend_rows().items()}
    assert funnels == {TOODLE: "toodle", second: "toodle", OTHER: None}
    spend = ledger.board_day(date(2026, 11, 1))["spend"]
    assert (spend["toodle_usd_cents"], spend["all_usd_cents"]) == (702, 1702)


def test_setting_the_campaign_list_later_labels_every_stored_day(db, graph, monkeypatch):
    monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    graph.add("2026-08-10", "4.87").add("2026-08-10", "1.00", OTHER).add("2026-10-15", "4.87").add("2026-11-01", "5.02")
    meta_sync.run(now=NOW)                                                    # the first run: 90 days, no Toodle
    assert {r["funnel"] for r in db.spend_rows().values()} == {None}
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TOODLE)
    graph.calls.clear()
    out = meta_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok" and graph.ranges() == [("2026-10-05", "2026-11-02")]    # 10 Aug is not read again
    rows = db.spend_rows()
    assert {k: r["funnel"] for k, r in rows.items()} == {
        (TOODLE, "2026-08-10"): "toodle", (OTHER, "2026-08-10"): None, (TOODLE, "2026-10-15"): "toodle",
        (TOODLE, "2026-11-01"): "toodle"}
    assert {k: r["spend_minor"] for k, r in rows.items()} == {
        (TOODLE, "2026-08-10"): 487, (OTHER, "2026-08-10"): 100, (TOODLE, "2026-10-15"): 487,
        (TOODLE, "2026-11-01"): 502}                                          # a label only: the money is untouched
    day = ledger.board_day(date(2026, 8, 10))["spend"]
    assert (day["toodle_usd_cents"], day["all_usd_cents"]) == (487, 587)


def test_a_campaign_taken_off_the_list_is_not_toodle_on_any_day(db, graph, monkeypatch):
    second = "120249191226470280"
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{TOODLE},{second}")
    graph.add("2026-08-10", "4.87").add("2026-08-10", "3.00", second).add("2026-11-01", "5.02")
    graph.add("2026-11-01", "3.00", second)
    meta_sync.run(now=NOW)
    assert {r["funnel"] for r in db.spend_rows().values()} == {"toodle"}
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TOODLE)
    meta_sync.run(now=NOW + timedelta(hours=1))
    assert {k: r["funnel"] for k, r in db.spend_rows().items()} == {
        (TOODLE, "2026-08-10"): "toodle", (second, "2026-08-10"): None, (TOODLE, "2026-11-01"): "toodle",
        (second, "2026-11-01"): None}
    assert ledger.board_day(date(2026, 8, 10))["spend"]["toodle_usd_cents"] == 487
    monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    meta_sync.run(now=NOW + timedelta(hours=2))
    assert {r["funnel"] for r in db.spend_rows().values()} == {None}           # no list: no Toodle spend anywhere


def test_relabelling_writes_only_the_labels_that_change(db, graph):
    graph.add("2026-08-10", "4.87").add("2026-08-10", "1.00", OTHER)
    meta_sync.run(now=NOW)
    before = {k: r["updated_at"] for k, r in db.spend_rows().items()}
    meta_sync.run(now=NOW + timedelta(hours=1))                               # the same list: 10 Aug untouched
    assert {k: r["updated_at"] for k, r in db.spend_rows().items()} == before
    patches = [dict(c.url.params) for c in db.calls if c.method == "PATCH" and c.url.path.endswith("/ad_spend_daily")]
    assert patches[-2:] == [
        {"source_id": "eq.meta_ads", "campaign_id": f"in.({TOODLE})", "or": "(funnel.is.null,funnel.neq.toodle)"},
        {"source_id": "eq.meta_ads", "funnel": "eq.toodle", "campaign_id": f"not.in.({TOODLE})"}]


def test_a_listed_campaign_with_no_spend_in_the_window_is_named_in_a_warning(db, graph, monkeypatch):
    typo = "120249191226470278"                                               # one digit off: Meta has no such campaign
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", typo)
    graph.add("2026-11-01", "5.02")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok"
    assert out["error"] == f"no spend seen for campaign {typo} since 2026-08-05: check BOARD_TOODLE_META_CAMPAIGN_IDS"
    src = db.sources["meta_ads"]
    assert src["last_error"] == out["error"] and src["last_error_at"] == src["last_ok_at"]     # a warning
    (run,) = db.runs("meta_sync")                         # what the board reads back: the list and its unseen ids
    assert (run["detail"]["toodle_campaigns"], run["detail"]["toodle_campaigns_unseen"]) == ([typo], [typo])
    assert run["detail"]["days"]["since"] == "2026-08-05"
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{TOODLE},{typo},120249191226470001")
    out = meta_sync.run(now=NOW + timedelta(hours=1))
    assert out["error"] == (f"no spend seen for campaigns 120249191226470001, {typo} since 2026-10-05: "
                            "check BOARD_TOODLE_META_CAMPAIGN_IDS")
    assert "Toodle opt-in" not in json.dumps(out["detail"]["warnings"])       # ids only, never a campaign's name
    many = ",".join(str(120249191226470001 + n) for n in range(5))
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", f"{TOODLE},{many}")
    out = meta_sync.run(now=NOW + timedelta(hours=2))
    assert out["error"] == ("no spend seen for campaigns 120249191226470001, 120249191226470002, "
                            "120249191226470003 and 2 more since 2026-10-05: check BOARD_TOODLE_META_CAMPAIGN_IDS")
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TOODLE)
    out = meta_sync.run(now=NOW + timedelta(hours=3))
    assert out["error"] is None and out["detail"]["toodle_campaigns_unseen"] == []   # every listed campaign has spend


def _kit_synced(monkeypatch, db) -> None:
    """Kit configured and synced past 1 Nov, so the stop rule can give a verdict on it."""
    bf.configure_connectors(monkeypatch, "kit")
    db.set_source("kit", measured_from="2026-01-01", synced_through="2026-11-02T11:55:00Z")


def test_a_campaign_list_set_after_a_meta_sync_has_no_toodle_number_until_the_next_run(db, graph, monkeypatch):
    # Meta synced while BOARD_TOODLE_META_CAMPAIGN_IDS was unset; then the owner sets it and redeploys. The
    # stored days keep the old labels until the next Meta run (06:30, 12:30 or Sync now), so until then the
    # board reads neither "$0.00" nor "no Toodle ad spend", and nothing is final. After it: $5.02, and STOP.
    _kit_synced(monkeypatch, db)
    monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    _toodle_days(graph, "2026-10-28", 5, "5.02")
    _optins("meta", 4)
    assert meta_sync.run(now=NOW)["status"] == "ok"
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TOODLE)
    view = board_day.day_view(date(2026, 11, 1))
    spend, cpl = view["numbers"]["spend"], view["numbers"]["cpl"]
    assert (spend["value"], spend["toodle_usd_cents"], spend["state"], spend["all_usd_cents"]) == \
        (None, None, "partial", 502)
    assert spend["note"].startswith("Toodle campaigns changed: waiting for the next Meta sync · ")
    assert (cpl["verdict"], cpl["value"], cpl["state"]) == (None, None, "partial")
    assert cpl["note"] == "Toodle campaigns changed: waiting for the next Meta sync"
    text = board_day.render_report(view)
    assert "$0.00" not in text and "no Toodle ad spend" not in text and "STOP" not in text
    assert meta_sync.run(now=NOW + timedelta(hours=1))["status"] == "ok"
    n = board_day.day_view(date(2026, 11, 1))["numbers"]
    assert (n["spend"]["value"], n["spend"]["state"]) == (502, "final")
    assert (n["cpl"]["verdict"], n["cpl"]["value"], n["cpl"]["state"], n["cpl"]["note"]) == \
        ("stop", 628, "final", "")


def test_a_mistyped_campaign_id_is_named_on_the_stop_rule_too(db, graph, monkeypatch):
    # One digit off: the listed id is no campaign of the account, so no spend is Toodle's. The run's
    # warning reaches the stop rule's no_spend verdict, by id; the verdict and its $0 stay.
    typo = "120249191226470278"
    _kit_synced(monkeypatch, db)
    monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", typo)
    _toodle_days(graph, "2026-10-28", 5, "5.02")
    _optins("meta", 4)
    out = meta_sync.run(now=NOW)
    warning = f"no spend seen for campaign {typo} since 2026-08-05: check BOARD_TOODLE_META_CAMPAIGN_IDS"
    assert (out["status"], out["error"]) == ("ok", warning)
    view = board_day.day_view(date(2026, 11, 1))
    spend, cpl = view["numbers"]["spend"], view["numbers"]["cpl"]
    assert (spend["value"], spend["state"], spend["all_usd_cents"]) == (0, "final", 502)
    assert spend["note"].endswith(f"last sync: {warning}")                      # the Meta line, as before
    assert (cpl["verdict"], cpl["state"], cpl["spend_usd_cents"], cpl["note"]) == ("no_spend", "final", 0, warning)
    lines = board_day.render_report(view).split("\n")
    assert lines[lines.index("Stop rule: no Toodle ad spend in the last 30 days") + 1] == f"  {warning}"
    assert "Toodle opt-in" not in json.dumps(view["numbers"])               # ids only, never a campaign's name


def test_without_toodle_campaign_ids_the_spend_is_read_with_a_warning(db, graph, monkeypatch):
    monkeypatch.delenv("BOARD_TOODLE_META_CAMPAIGN_IDS")
    graph.add("2026-11-01", "5.02")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok"
    assert out["error"] == "BOARD_TOODLE_META_CAMPAIGN_IDS is not set, so no Meta spend counts as Toodle spend"
    assert out["detail"]["warnings"] == [out["error"]]
    assert db.spend_rows()[(TOODLE, "2026-11-01")]["funnel"] is None
    src = db.sources["meta_ads"]
    assert src["last_error"] == out["error"] and src["last_error_at"] == src["last_ok_at"]   # a warning
    assert ledger.board_day(date(2026, 11, 1))["cpl"]["verdict"] == "no_spend"


def test_a_revised_day_replaces_the_one_pulled_before(db, graph):
    graph.add("2026-11-01", "5.02", clicks="9")
    meta_sync.run(now=NOW)
    graph.add("2026-11-01", "5.10", clicks="11")
    out = meta_sync.run(now=NOW + timedelta(hours=6))
    rows = db.spend_rows()
    row = rows[(TOODLE, "2026-11-01")]
    assert len(rows) == 1 and (row["spend_minor"], row["spend_usd_cents"], row["link_clicks"]) == (510, 510, 11)
    assert row["job_run_id"] == out["id"]


def test_meta_lead_counts_are_never_added_twice():
    def leads(*pairs, **kw):
        return meta_sync.platform_leads([{"action_type": t, "value": v, **kw} for t, v in pairs])
    assert leads(("link_click", "23"), ("offsite_conversion.fb_pixel_lead", "2"), ("lead", "3")) == 3
    assert leads(("onsite_conversion.lead_grouped", "3"), ("leadgen_grouped", "3"),
                 ("offsite_conversion.fb_pixel_lead", "2")) == 5                # on Meta once, plus the website
    assert leads(("leadgen_grouped", "4")) == 4
    assert leads(("offsite_conversion.fb_pixel_lead", "2"), ("offsite_conversion.fb_pixel_lead", "9")) == 2
    assert leads(("onsite_conversion.lead_grouped", "1.6"), ("offsite_conversion.fb_pixel_lead", "x")) == 2
    assert leads(("link_click", "23")) is None and meta_sync.platform_leads(None) is None
    assert leads(("lead", "0")) == 0


def test_meta_lead_counts_ride_along_as_a_cross_check(db, graph):
    graph.add("2026-11-01", "5.02", actions=[{"action_type": "link_click", "value": "9"},
                                             {"action_type": "offsite_conversion.fb_pixel_lead", "value": "1"},
                                             {"action_type": "onsite_conversion.lead_grouped", "value": "1"}])
    graph.add("2026-11-02", "1.00", impressions=None, clicks=None)             # no actions, no counts
    meta_sync.run(now=NOW)
    rows = db.spend_rows()
    assert rows[(TOODLE, "2026-11-01")]["platform_leads"] == 2
    assert (rows[(TOODLE, "2026-11-02")]["platform_leads"], rows[(TOODLE, "2026-11-02")]["impressions"],
            rows[(TOODLE, "2026-11-02")]["link_clicks"]) == (None, 0, 0)


def test_spend_rows_skip_days_outside_the_window_and_keep_one_row_a_campaign_day():
    def row(day, spend, **kw):
        return {"campaign_id": TOODLE, "spend": spend, "date_start": day, "date_stop": day, **kw}
    rows, counts = meta_sync.spend_rows([row("2026-11-01", "5.02"), row("2026-11-01", "5.10"),
                                         row("2026-10-01", "1.00")],
                                        "USD", frozenset({TOODLE}), date(2026, 10, 27), date(2026, 11, 2))
    assert [(r.day.isoformat(), r.spend_minor, r.funnel) for r in rows] == [("2026-11-01", 510, "toodle")]
    assert (counts["outside_window"], counts["duplicates"], counts["rows_read"]) == (1, 1, 3)
    window = ("USD", frozenset(), date(2026, 10, 27), date(2026, 11, 2))
    for bad, said in ((row("2026-11-01", "1,234.00"), "a spend amount the board cannot read"),
                      (row("2026-11-01", "-1.00"), "a spend amount the board cannot read"),
                      (row("2026-11-01", "1.00", date_stop="2026-11-02"), "over more than one day"),
                      (row("2026-11-01", "1.00", account_currency="EUR"), "spend in EUR for an account in USD"),
                      (row("2026-11-01", "1.00", impressions="12.5"), "impressions the board cannot read"),
                      ({"spend": "1.00", "date_start": "2026-11-01"}, "without a campaign id"),
                      (row("1 Nov", "1.00"), "without a day")):
        with pytest.raises(meta_sync.MetaSyncError, match=said):
            meta_sync.spend_rows([bad], *window)


def test_a_row_meta_wrote_oddly_fails_the_run_and_writes_nothing(db, graph):
    graph.add("2026-11-01", "5.02").add("2026-11-02", "1,234.00")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == (f"Meta sent a spend amount the board cannot read for campaign {TOODLE} on "
                            "2026-11-02, so nothing was written")
    src = db.sources["meta_ads"]
    assert db.spend_rows() == {} and src["synced_through"] is None and src["measured_from"] is None
    assert src["last_error"] == out["error"] and db.runs("meta_sync")[0]["status"] == "failed"


# ─── the account's facts ────────────────────────────────────────────────────

def test_an_account_whose_ads_cannot_run_is_still_read_with_a_warning(db, graph):
    graph.info["account_status"] = 3
    graph.add("2026-11-01", "5.02")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and out["error"] == "the ad account is unpaid (status 3), so its ads cannot run"
    assert len(db.spend_rows()) == 1 and out["detail"]["account_status"] == 3
    assert meta_sync.status_warning(9) is None and meta_sync.status_warning(None) is None
    assert meta_sync.status_warning(42) == "the ad account is not active (status 42), so its ads cannot run"


@pytest.mark.parametrize("change, error", [
    ({"timezone_name": None}, "Meta did not give the ad account's time zone, so its days cannot be read"),
    ({"timezone_name": "Mars/Olympus_Mons"},
     "Meta gave the ad account a time zone this server does not know (Mars/Olympus_Mons)"),
    ({"timezone_name": "UTC+3 (Moscow)"}, "Meta gave the ad account a time zone name the board cannot read"),
    ({"currency": None}, "Meta did not give the ad account's currency, so its spend cannot be read"),
])
def test_an_account_without_a_usable_zone_or_currency_fails_before_any_spend_is_read(db, graph, change, error):
    graph.info.update(change)
    out = meta_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("failed", error)
    assert graph.insights_calls() == [] and db.sources["meta_ads"]["last_error"] == error


# ─── Meta refusing or failing ───────────────────────────────────────────────

def test_a_rate_limit_is_waited_out_then_read(db, graph):
    graph.add("2026-11-01", "5.02")
    graph.fail_next = [throttle(), throttle(17, 2446079)]
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and graph.sleeps == [5.0, 15.0]
    assert db.spend_rows()[(TOODLE, "2026-11-01")]["spend_minor"] == 502


def test_a_rate_limit_that_lasts_fails_the_run_after_3_retries(db, graph):
    graph.fail_next = [throttle()] * 4
    out = meta_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == ("Meta is rate limiting this app or ad account (code 80000) after 3 retries; "
                            "the next run tries again")
    assert graph.sleeps == [5.0, 15.0, 30.0] and len(graph.calls) == 4
    meta_error = out["detail"]["meta_error"]
    assert (meta_error["code"], meta_error["subcode"], meta_error["retries"]) == (80000, 2446079, 3)
    assert "estimated_time_to_regain_access" in meta_error["usage"]["x-business-use-case-usage"]
    assert db.sources["meta_ads"]["last_error"] == out["error"] and db.spend_rows() == {}


def test_a_temporary_error_is_tried_again(db, graph):
    graph.fail_next = [(500, {"message": "An unexpected error has occurred. Please retry your request later.",
                              "type": "OAuthException", "code": 2, "is_transient": True}, {})]
    assert meta_sync.run(now=NOW)["status"] == "ok" and graph.sleeps == [2.0]


def test_no_answer_fails_the_run_with_a_plain_sentence(db, graph):
    graph.raise_next = [_refused] * 4
    out = meta_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == "Meta could not be reached after 3 retries; the next run tries again"


def test_a_refused_token_is_stored_without_the_token(db, graph, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    expired = "FAKEMETAexpiredInsightsToken9z8y7x6w5v4u3t2s1r0q"
    monkeypatch.setenv("META_INSIGHTS_TOKEN", expired)
    db.set_source("meta_ads", measured_from="2026-08-05", synced_through="2026-11-02T06:00:00Z")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "failed"
    assert out["error"] == ("Meta refused the access token (code 190): it is not valid or has expired. "
                            "Make a new token and set META_INSIGHTS_TOKEN")
    assert len(graph.calls) == 2                                               # the header, then the parameter
    (run,) = db.runs("meta_sync")
    assert run["status"] == "failed" and run["error"] == out["error"]
    assert run["detail"]["meta_error"]["said"] == "Error validating access token: the token [hidden] has expired."
    stored = [json.dumps(out), json.dumps(run["detail"]), run["error"], db.sources["meta_ads"]["last_error"],
              caplog.text]
    for text in stored:
        assert expired not in text and expired[:12] not in text
    assert db.sources["meta_ads"]["synced_through"] == datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("error, said", [
    ({"code": 100, "error_subcode": 33, "message": "Unsupported get request."},
     ("Meta cannot find the ad account, or the token cannot read it (code 100): check AD_ACCOUNT_ID and the "
      "token's access to the account")),
    ({"code": 200, "message": "Permissions error"},
     "Meta refused access (code 200): the token needs ads_read and access to the ad account"),
    ({"code": 2635, "message": "(#2635) You are calling a deprecated version of the Ads API."},
     "Meta no longer serves API version v26.0 (code 2635): set META_GRAPH_VERSION to v26.0"),
    ({"code": 100, "message": "API calls from the server require an appsecret_proof argument"},
     "Meta wants appsecret_proof for this token's app (code 100): set META_APP_SECRET to that app's secret"),
    ({"code": 100, "error_subcode": 1504018, "message": "Request Timed Out"},
     "Meta timed out reading one day of spend (code 100); the next run tries again"),
    ({"code": 803, "message": "Some of the aliases you requested do not exist"},
     "Meta refused the read (HTTP 400, code 803)"),
])
def test_each_refusal_reads_as_a_plain_sentence(db, graph, error, said):
    graph.fail_next = [(400, {"type": "OAuthException", **error}, {})]
    out = meta_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("failed", said)
    assert graph.sleeps == []                                                  # none is worth trying again


def test_an_old_graph_version_is_named_in_a_warning(db, graph, monkeypatch):
    monkeypatch.setenv("META_GRAPH_VERSION", "v19.0")
    graph.served_version = "v24.0"                                             # Meta upgraded the call
    graph.add("2026-11-01", "5.02")
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and len(db.spend_rows()) == 1
    assert out["error"] == "META_GRAPH_VERSION is v19.0, which Meta no longer serves for ads: set it to v26.0"
    assert out["detail"]["served_version"] == "v24.0"
    assert urlsplit(graph.calls[0].url).path.startswith("/v19.0/")


def test_an_upgraded_answer_is_a_warning(db, graph, monkeypatch):
    monkeypatch.setenv("META_GRAPH_VERSION", "v25.0")
    graph.served_version = "v26.0"
    graph.add("2026-11-01", "5.02")
    out = meta_sync.run(now=NOW)
    assert out["error"] == "Meta answered from v26.0, not v25.0: set META_GRAPH_VERSION to v26.0"
    monkeypatch.setenv("META_GRAPH_VERSION", "v26.0")
    graph.served_version, graph.extra_headers = None, {"X-Ad-Api-Version-Warning": "auto-upgraded"}
    out = meta_sync.run(now=NOW + timedelta(hours=1))
    assert out["error"] == "Meta answered from a newer version, not v26.0: set META_GRAPH_VERSION to v26.0"


def test_appsecret_proof_goes_with_meta_app_secret_and_is_dropped_when_it_is_another_apps(db, graph, monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    out = meta_sync.run(now=NOW)
    assert out["detail"]["appsecret_proof"] == "sent"
    assert all(_query(c)["appsecret_proof"] == [_proof(APP_SECRET)] for c in graph.calls)
    monkeypatch.setenv("META_APP_SECRET", "another-apps-secret-00000000000")
    out = meta_sync.run(now=NOW + timedelta(hours=1))
    assert out["status"] == "ok" and out["detail"]["appsecret_proof"].startswith("dropped")
    assert "another-apps-secret" not in json.dumps(out)


def test_the_ads_token_is_used_only_without_the_insights_token(db, graph, monkeypatch):
    monkeypatch.delenv("META_INSIGHTS_TOKEN")
    monkeypatch.setenv("META_ACCESS_TOKEN", TOKEN)
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["token"] == "META_ACCESS_TOKEN"


def test_pages_read_with_the_token_as_a_parameter_leave_it_nowhere(db, graph, caplog):
    caplog.set_level(logging.DEBUG)
    graph.header_auth = False                                                  # every `next` link then holds it
    for d in _days("2026-10-27", 7):
        graph.add(d, "5.02")
    graph.page_size = 2
    out = meta_sync.run(now=NOW)
    assert out["status"] == "ok" and out["detail"]["token_sent_as"] == "parameter" and len(db.spend_rows()) == 7
    (run,) = db.runs("meta_sync")
    for text in (json.dumps(out), json.dumps(run["detail"]), caplog.text):
        assert TOKEN not in text and "graph.facebook.com/v26.0/act_" + ACCOUNT + "/insights?" not in text


# ─── claims, the database, the source ───────────────────────────────────────

def test_the_database_down_fails_the_run_before_any_call_to_meta(db, graph):
    db.down = True
    out = meta_sync.run(now=NOW)
    assert out["status"] == "failed" and out["error"].startswith("database:") and graph.calls == []


def test_one_run_at_a_time(db, graph):
    db._rpc_board_claim_run("meta_sync", "an-earlier-run", "schedule", "meta_ads")    # still running
    out = meta_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("busy", "another Meta sync is running") and graph.calls == []


def test_a_disabled_source_is_skipped(db, graph):
    db.set_source("meta_ads", enabled=False)
    out = meta_sync.run(now=NOW)
    assert (out["status"], out["error"]) == ("skipped", "the meta_ads source is disabled") and graph.calls == []
    (run,) = db.runs("meta_sync")
    assert run["status"] == "skipped" and run["finished_at"] is not None


def test_the_watermark_never_moves_back(db, graph):
    meta_sync.run(now=NOW + timedelta(hours=2))
    assert meta_sync.run(now=NOW)["status"] == "ok"                            # started earlier, finished later
    assert db.sources["meta_ads"]["synced_through"] == NOW + timedelta(hours=2)


def test_a_meta_day_is_final_once_it_has_ended_in_the_accounts_zone(db, graph):
    graph.add("2026-11-01", "5.02", clicks="9")
    meta_sync.run(now=NOW)

    def meta(day):
        return next(s for s in ledger.board_day(day)["sources"] if s["id"] == "meta_ads")
    assert (meta(date(2026, 11, 1))["state"], meta(date(2026, 11, 1))["day_tz"]) == ("final", LA)
    assert meta(date(2026, 11, 2))["state"] == "partial"                       # 04:00 on 2 Nov in Los Angeles
    assert meta(date(2026, 8, 4))["state"] == "not_connected"                  # before measured_from
    spend = ledger.board_day(date(2026, 11, 1))["spend"]
    assert (spend["toodle_usd_cents"], spend["toodle_link_clicks"], spend["unconverted_rows"]) == (502, 9, 0)


# ─── the stop rule, from Meta's answer to board_day ─────────────────────────

def _toodle_days(graph, first: str, n: int, spend: str, currency: str = "USD") -> None:
    for d in _days(first, n):
        graph.add(d, spend, currency=currency)


_subscribers = itertools.count(100)


def _optins(channel, n: int) -> None:
    """n Toodle opt-ins on 28, 29, 30 and 31 Oct in New York, through the Kit
    path, each from a new subscriber."""
    tags = ("toodle", "meta_ad") if channel == "meta" else ("toodle",)
    ledger.ingest_leads("kit", None, [bf.optin(next(_subscribers), f"2026-10-{28 + i % 4}T16:00:00Z", channel,
                                               tags=tags) for i in range(n)])


@pytest.mark.parametrize("case, verdict", [
    ("Meta spend, none of it Toodle's", "no_spend"),
    ("3 spend days", "collecting"),
    ("$25.10 over 5 days for 4 Meta opt-ins", "stop"),
    ("$15.00 over 5 days for 4 Meta opt-ins", "ok"),
    ("Toodle opt-ins, none tagged meta", "check_tags"),
    ("a euro account with no ECB rate yet", "check_currency"),
])
def test_the_stop_rule_reads_the_synced_spend(db, graph, case, verdict):
    if case == "Meta spend, none of it Toodle's":
        graph.add("2026-11-01", "10.00", OTHER)
        _optins("meta", 1)
    elif case == "3 spend days":
        _toodle_days(graph, "2026-10-30", 3, "5.02")
        _optins("meta", 4)
    elif case == "$25.10 over 5 days for 4 Meta opt-ins":
        _toodle_days(graph, "2026-10-28", 5, "5.02")
        _optins("meta", 4)
        _optins("organic", 1)
    elif case == "$15.00 over 5 days for 4 Meta opt-ins":
        _toodle_days(graph, "2026-10-28", 5, "3.00")
        _optins("meta", 4)
    elif case == "Toodle opt-ins, none tagged meta":
        _toodle_days(graph, "2026-10-28", 5, "5.02")
        _optins("organic", 2)
        _optins(None, 1)
    elif case == "a euro account with no ECB rate yet":
        graph.info.update(currency="EUR", timezone_name="Europe/Berlin")
        _toodle_days(graph, "2026-10-28", 5, "4.50", currency="EUR")
        _optins("meta", 4)
    assert meta_sync.run(now=NOW)["status"] == "ok"
    cpl = ledger.board_day(date(2026, 11, 1))["cpl"]
    assert cpl["verdict"] == verdict
    if verdict == "stop":
        assert (cpl["spend_days"], cpl["first_day"], cpl["last_day"], cpl["spend_usd_cents"]) == \
            (5, "2026-10-28", "2026-11-01", 2510)
        assert (cpl["meta_optins"], cpl["toodle_optins"], cpl["cpl_meta_usd_cents"], cpl["cpl_all_usd_cents"],
                cpl["stop_above_cents"]) == (4, 5, 628, 502, 500)            # $6.28 a Meta opt-in, above $5
    if verdict == "ok":
        assert cpl["cpl_meta_usd_cents"] == 375
    if verdict == "collecting":
        assert cpl["spend_days"] == 3
    if verdict == "check_currency":
        assert cpl["unconverted_spend_rows"] == 5
