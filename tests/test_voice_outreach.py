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


def test_dial_campaign_dry_run_preview(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(vo, "_within_business_hours", lambda now=None: True)
    for k in ("VAPI_API_KEY", "VAPI_PHONE_NUMBER_ID"):
        monkeypatch.delenv(k, raising=False)
    base = tmp_path / "leadgen" / "dental-boston"
    base.mkdir(parents=True)
    (base / "leads.json").write_text(json.dumps([
        {"name": "A Dental", "phone": "(617) 555-0101"},
        {"name": "No Phone Co", "phone": ""},
        {"name": "B Dental", "phone": "617-555-0102"}]))
    r = vo.dial_campaign("dental-boston")
    assert r["status"] == "dry_run_preview"          # unarmed -> NO calls
    assert r["with_phone"] == 2 and r["queued_this_run"] == 2
    assert all(q["outcome"] == "dry_run" for q in r["queue"])


def test_dial_campaign_unknown_and_no_leads(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert vo.dial_campaign("nope")["status"] == "unknown_campaign"
    assert vo.dial_campaign("dental-boston")["status"] == "no_leads"


def test_dial_campaign_registration_gate(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(vo, "_within_business_hours", lambda now=None: True)
    monkeypatch.setenv("VAPI_API_KEY", "x")                     # -> armed
    monkeypatch.delenv("VOICE_BUSINESS_REGISTERED", raising=False)
    monkeypatch.setattr(vo, "place_call", lambda *a, **k: {"status": "dry_run"})  # no network
    base = tmp_path / "leadgen" / "dental-boston"
    base.mkdir(parents=True)
    (base / "leads.json").write_text(json.dumps([{"name": "A", "phone": "(617) 555-0101"}]))
    # armed + REAL leads + unregistered -> HARD blocked by the compliance gate
    assert vo.dial_campaign("dental-boston", confirm=True, live=True)["status"] == "blocked"
    # redirect_to (self-test to your own phone) bypasses the gate
    assert vo.dial_campaign("dental-boston", confirm=True, live=True,
                            redirect_to="+15551234567")["status"] == "SELF_TEST_DIALING"
