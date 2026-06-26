import core.voice_outreach as vo


def test_assistant_is_compliant_and_carries_offer():
    a = vo.compose_assistant("a modern website + online booking", "Boston Dental")
    # AI disclosure + recording notice + opt-out are in the opening line
    fm = a["firstMessage"].lower()
    assert "ai assistant" in fm and "recorded" in fm and "remove me" in fm
    sys = a["model"]["messages"][0]["content"].lower()
    assert "never claim to be human" in sys
    assert "a modern website + online booking" in sys
    assert "boston dental" in sys
    assert a["recordingEnabled"] is True


def test_place_call_dry_run_when_unarmed(monkeypatch):
    for k in ("VAPI_API_KEY", "VAPI_PHONE_NUMBER_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(vo, "_within_business_hours", lambda now=None: True)
    r = vo.place_call("+16175550142", "demo", confirm=True, live=True)
    assert r["status"] == "dry_run"
    assert "VAPI_API_KEY" in r["reason"]  # honestly names what's missing


def test_suppressed_number_blocked(monkeypatch, tmp_path, ):
    monkeypatch.setattr(vo, "_within_business_hours", lambda now=None: True)
    monkeypatch.setattr(vo, "_suppressed_numbers", lambda: {"6175550142"})
    r = vo.place_call("(617) 555-0142", "demo", confirm=True, live=True)
    assert r["status"] == "blocked" and r["reason"] == "suppressed_or_opted_out"


def test_invalid_number_blocked(monkeypatch):
    monkeypatch.setattr(vo, "_within_business_hours", lambda now=None: True)
    assert vo.place_call("123", "demo", confirm=True, live=True)["reason"] == "invalid_number"


def test_self_test_needs_operator_number(monkeypatch):
    monkeypatch.delenv("VOICE_TEST_NUMBER", raising=False)
    assert vo.self_test()["status"] == "blocked"
