"""POST /api/board/sync/{source}, the page's "Sync now": an interactive sync
answers within 60 seconds, because Cloudflare cuts a request at about 100.

The route starts the connector's run in a worker thread of its own and waits
routes.SYNC_WAIT seconds (50) at most. A run that ends in time gets the answer
it always had (200 ok, 409 busy, 503 skipped, 502 failed); 429 still comes
first, once a minute per source. A run that does not end in time gets 202
"running" and carries on in the background, holding its claim, and finishes
like any other run. No network: run() is replaced, or Kit is a small fake
that holds its answer until the test lets it go; Supabase is faked in
tests/board_fakes.py."""
import json
import logging
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from core import kit as core_kit
from core.board import routes
from core.board.connectors import instantly_sync, kit_sync, meta_sync, stripe_sync
from tests import board_fakes as bf

SAME_ORIGIN = {"Origin": "http://testserver"}
CONNECTORS = {"stripe": stripe_sync, "kit": kit_sync, "instantly": instantly_sync, "meta_ads": meta_sync}
RUNNING = "Still running. The board updates when it finishes."


@pytest.fixture(autouse=True)
def no_connector_settings(monkeypatch):
    bf.clear_connectors(monkeypatch)


@pytest.fixture
def owner(monkeypatch):
    fake = bf.install(monkeypatch)
    monkeypatch.setattr(routes, "_last_sync", {})
    return bf.client(monkeypatch), {**bf.cookie(fake.add_session()), **SAME_ORIGIN}


class HeldRun:
    """Stands in for one connector's run(trigger, days): it starts, then waits
    for `release` (5 s at most), then ends with `answer`. `started` and
    `finished` tell the test where it is, from any thread."""

    def __init__(self, monkeypatch, source: str, answer: str = "ok", hold: bool = True):
        self.source, self.answer = source, answer
        self.calls: list[tuple] = []
        self.started, self.finished, self.release = threading.Event(), threading.Event(), threading.Event()
        if not hold:
            self.release.set()
        monkeypatch.setattr(CONNECTORS[source], "run", self.run)

    def run(self, trigger="schedule", days=None, now=None):
        self.calls.append((trigger, days))
        self.started.set()
        self.release.wait(5)
        self.finished.set()
        return {"id": f"run-{self.source}", "source_id": self.source, "trigger_kind": trigger,
                "status": self.answer, "error": None if self.answer == "ok" else f"{self.source} {self.answer}"}


def test_the_route_waits_at_most_50_seconds():
    assert 0 < routes.SYNC_WAIT <= 50                  # an answer well inside Cloudflare's ~100 s


@pytest.mark.parametrize("source", sorted(CONNECTORS))
def test_a_run_that_outlasts_the_wait_answers_202_and_still_finishes(owner, monkeypatch, source):
    client, headers = owner
    monkeypatch.setattr(routes, "SYNC_WAIT", 0.2, raising=False)
    held = HeldRun(monkeypatch, source)
    began = time.monotonic()
    r = client.post(f"/api/board/sync/{source}?days=3", headers=headers)
    took = time.monotonic() - began
    assert r.status_code == 202, r.text
    assert r.json() == {"source": source, "status": "running", "note": RUNNING}
    assert "no-store" in r.headers["cache-control"]
    assert took < 3                                    # the run itself waits 5 s unless it is let go
    assert held.started.wait(5) and not held.finished.is_set()        # it carries on in the background
    held.release.set()
    assert held.finished.wait(5)                       # and ends on its own
    assert held.calls == [("owner", 3)]


@pytest.mark.parametrize("source", sorted(CONNECTORS))
def test_a_run_that_ends_in_time_gets_the_answer_it_always_had(owner, monkeypatch, source):
    client, headers = owner
    for answer, code in (("ok", 200), ("busy", 409), ("skipped", 503), ("failed", 502)):
        monkeypatch.setattr(routes, "_last_sync", {})
        held = HeldRun(monkeypatch, source, answer, hold=False)
        r = client.post(f"/api/board/sync/{source}", headers=headers)
        assert r.status_code == code, (answer, r.text)
        body = r.json()
        assert (body["status"], body["source_id"], body["trigger_kind"]) == (answer, source, "owner")
        assert body["error"] == (None if answer == "ok" else f"{source} {answer}")
        assert "no-store" in r.headers["cache-control"] and held.finished.is_set()


def test_a_run_that_raises_is_a_plain_failure_and_its_text_stays_out(owner, monkeypatch, caplog):
    client, headers = owner
    secret = "kit_FAKErouteTestKey0123456789"                  # fake

    def boom(trigger="schedule", days=None, now=None):
        raise RuntimeError(f"connection to https://api.kit.com/v4/tags?api_key={secret} failed")

    monkeypatch.setattr(kit_sync, "run", boom)
    r = client.post("/api/board/sync/kit", headers=headers)
    assert r.status_code == 502
    assert r.json() == {"source_id": "kit", "status": "failed", "error": "the sync stopped unexpectedly"}
    assert secret not in caplog.text and "api.kit.com" not in caplog.text
    assert "kit sync stopped unexpectedly (RuntimeError)" in caplog.text


def test_the_owner_and_origin_checks_come_before_any_run(owner, monkeypatch):
    client, headers = owner
    held = HeldRun(monkeypatch, "kit", hold=False)
    url = "/api/board/sync/kit"
    assert client.post(url, headers=SAME_ORIGIN).status_code == 401                          # no session
    assert client.post(url, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, headers={"Cookie": headers["Cookie"]}).status_code == 403          # no Origin
    assert client.post("/api/board/sync/kdp", headers=headers).status_code == 404
    assert held.calls == []


# ─── the claim, with the real Kit connector ─────────────────────────────────

def _kit_answer(status: int, body: dict) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body).encode()
    r.headers = CaseInsensitiveDict({"Content-Type": "application/json"})
    r.encoding = "utf-8"
    return r


class SlowKit:
    """Kit's tag list and tag subscribers (none), each answer held until
    `release` is set: a Kit that answers slowly."""

    def __init__(self):
        self.release = threading.Event()
        self.calls: list[str] = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append(urlsplit(url).path)
        assert self.release.wait(5), "the test never let Kit answer"
        if urlsplit(url).path == "/v4/tags":
            return _kit_answer(200, {"tags": [{"id": 11, "name": "toodle"}],
                                     "pagination": {"has_next_page": False}})
        return _kit_answer(200, {"subscribers": [], "pagination": {"has_next_page": False}})


def _wait_for(check, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_a_run_still_going_holds_its_claim_and_the_minute(owner, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    client, headers = owner
    db = bf.install_board(monkeypatch)
    kit = SlowKit()
    monkeypatch.setenv("KIT_API_KEY", bf.KIT_KEY)
    monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", "toodle:")
    monkeypatch.setattr(core_kit, "requests",
                        SimpleNamespace(request=kit.request, RequestException=requests.RequestException))
    monkeypatch.setattr(kit_sync, "_RATE_PER_SEC", 1e6)
    monkeypatch.setattr(routes, "SYNC_WAIT", 0.2, raising=False)
    try:
        r = client.post("/api/board/sync/kit", headers=headers)
        assert (r.status_code, r.json()["status"]) == (202, "running")
        assert _wait_for(lambda: kit.calls)                                          # past its claim, at Kit
        (run,) = db.runs("kit_sync")
        assert (run["status"], run["trigger_kind"]) == ("running", "owner")          # claimed, still going
        again = client.post("/api/board/sync/kit", headers=headers)
        assert again.status_code == 429 and int(again.headers["retry-after"]) >= 1    # within the minute
        monkeypatch.setattr(routes, "_last_sync", {})                                 # a minute later
        busy = client.post("/api/board/sync/kit", headers=headers)
        assert busy.status_code == 409 and busy.json()["error"] == "another Kit sync is running"
        assert len(db.runs("kit_sync")) == 1
    finally:
        kit.release.set()
    assert _wait_for(lambda: db.runs("kit_sync")[0]["status"] != "running")
    (run,) = db.runs("kit_sync")
    assert run["status"] == "ok" and run["finished_at"] is not None                  # it finished normally
    assert db.sources["kit"]["synced_through"] is not None and db.sources["kit"]["measured_from"] is not None
    monkeypatch.setattr(routes, "_last_sync", {})
    after = client.post("/api/board/sync/kit", headers=headers)
    assert (after.status_code, after.json()["status"]) == (200, "ok")                  # the claim is free again
