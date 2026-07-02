"""Operator control cockpit — portfolio-level 'watch + give direction' surface.

Covers the endpoints behind the Portfolio HQ '🎛 Control' tab:
  /control · /run/{slug} (preview) · /artifacts · /orchestrator · /sweep · /approvals

Every run() here must be preview/dry-run safe: it proves each loop end-to-end and
refreshes artifacts WITHOUT spending money or firing real actions.
"""


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_KEY", "test-key-123")
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # offline safety net: any LLM call returns a canned draft (adapters prefer the
    # committed GTM kit anyway, but this guarantees no network in CI).
    import core.base_bot as bb
    monkeypatch.setattr(bb.BaseBot, "claude",
                        lambda self, prompt, **kw: "DRAFTED", raising=False)
    from fastapi.testclient import TestClient
    import core.api as mod
    # the api_key middleware freezes _API_KEY at import; pin it so this test passes
    # regardless of which test imported core.api first.
    monkeypatch.setattr(mod, "_API_KEY", "test-key-123", raising=False)
    return TestClient(mod.app, raise_server_exceptions=False)


H = {"X-API-Key": "test-key-123"}


def _seed():
    from core.portfolio import seed
    seed.seed_all_loops()


def test_control_overview_and_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed()
    j = c.get("/api/narai/portfolio/control", headers=H).json()
    assert set(j) >= {"orchestrator", "businesses", "pending_approvals"}
    assert len(j["businesses"]) == 10
    assert j["orchestrator"]["enabled"] in (True, False)
    assert j["orchestrator"]["kill"] in (True, False)
    b0 = j["businesses"][0]
    assert set(b0) >= {"slug", "name", "completed", "pending", "armed", "blockers"}
    # unauthenticated is rejected
    assert c.get("/api/narai/portfolio/control").status_code in (401, 403)


def test_run_preview_completes_loop_and_lists_artifacts(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed()
    j = c.post("/api/narai/portfolio/run/n8n", headers=H).json()
    assert j["slug"] == "n8n"
    assert j["steps_total"] == 9
    # 6 GREEN steps execute (draft artifacts) · 3 auto_capped queue for approval
    assert len(j["completed"]) == 6
    assert len(j["pending"]) == 3
    assert j["artifacts"]["research"] is True
    assert j["artifacts"]["leads"] is True
    assert j["artifacts"]["pack"] is True
    # whitelist
    assert c.post("/api/narai/portfolio/run/bogus", headers=H).status_code == 404


def test_leads_preview_forces_dry_run_even_with_live_key(monkeypatch, tmp_path):
    # THE safety guarantee: a real Places key present, but preview beats it → no API call.
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "FAKE-would-cost-money")
    from core.portfolio.adapters.leads import LeadsAdapter
    from core.portfolio.actions import Action, ActionClass
    a = Action(verb="generate_lead_list", agent="", action_class=ActionClass.GREEN,
               preconditions=[], business="n8n", payload={"preview": True, "limit": 3})
    out = LeadsAdapter().run(a)
    assert out["mode"] == "dry_run"


def test_artifact_view_whitelisted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed()
    c.post("/api/narai/portfolio/run/n8n", headers=H)
    d = c.get("/api/narai/portfolio/artifacts/n8n/research", headers=H).json()
    assert d["kind"] == "research" and len(d["content"]) > 0
    # unknown kind + unknown business are both 404 (no arbitrary path read)
    assert c.get("/api/narai/portfolio/artifacts/n8n/etc-passwd", headers=H).status_code == 404
    assert c.get("/api/narai/portfolio/artifacts/bogus/research", headers=H).status_code == 404


def test_orchestrator_controls(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.post("/api/narai/portfolio/orchestrator?action=enable",
                  headers=H).json()["orchestrator"]["enabled"] is True
    assert c.post("/api/narai/portfolio/orchestrator?action=disable",
                  headers=H).json()["orchestrator"]["enabled"] is False
    assert c.post("/api/narai/portfolio/orchestrator?action=kill",
                  headers=H).json()["orchestrator"]["kill"] is True
    assert c.post("/api/narai/portfolio/orchestrator?action=unkill",
                  headers=H).json()["orchestrator"]["kill"] is False
    assert c.post("/api/narai/portfolio/orchestrator?action=bogus",
                  headers=H).status_code == 400


def test_sweep_is_preview_over_all_ten(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed()
    j = c.post("/api/narai/portfolio/sweep", headers=H).json()
    assert j["status"] == "preview_swept"
    assert len(j["ticked"]) == 10


def test_approvals_queue_and_resolve(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed()
    # running the loop queues the 3 auto_capped steps for sign-off
    c.post("/api/narai/portfolio/run/n8n", headers=H)
    ap = c.get("/api/narai/portfolio/approvals", headers=H).json()
    assert ap["count"] >= 1
    aid = ap["pending"][0]["id"]
    r = c.post(f"/api/narai/portfolio/approvals/{aid}?decision=approved", headers=H).json()
    assert r["status"] == "ok"
    # resolved item is gone from the pending queue
    ap2 = c.get("/api/narai/portfolio/approvals", headers=H).json()
    assert all(x["id"] != aid for x in ap2["pending"])
    # a second resolve of the same id is a no-op (compare-and-set from 'pending' fails)
    r2 = c.post(f"/api/narai/portfolio/approvals/{aid}?decision=rejected", headers=H).json()
    assert r2["status"] == "not_pending"
    # bad decision rejected
    assert c.post(f"/api/narai/portfolio/approvals/{aid}?decision=maybe",
                  headers=H).status_code == 400


def test_hq_html_has_control_tab_and_no_key_leak(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    html = c.get("/admin/portfolio-hq").text
    assert "🎛 Control" in html
    assert "loadControl" in html
    # the served page must never contain the real key
    assert "test-key-123" not in html
