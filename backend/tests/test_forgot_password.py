"""Password-reset request: always a neutral 202 (anti-enumeration), and it
actually calls Supabase recover when configured."""


def test_forgot_password_is_neutral_202(client):
    # No Supabase config in tests -> request_password_reset raises, is swallowed,
    # and the endpoint still returns the neutral 202 (can't probe email existence).
    r = client.post("/auth/forgot-password", json={"email": "whoever@example.com"})
    assert r.status_code == 202
    assert "reset link has been sent" in r.json()["message"]


def test_forgot_password_rejects_bad_email(client):
    r = client.post("/auth/forgot-password", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_request_password_reset_calls_supabase_recover(monkeypatch):
    import app.services.supabase_auth as sa

    calls = {}

    def fake_post(url, **kw):
        calls["url"] = url
        calls["json"] = kw.get("json")
        class _R:  # minimal httpx.Response stand-in
            status_code = 200
        return _R()

    monkeypatch.setattr(sa.settings, "SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setattr(sa.settings, "SUPABASE_SECRET_KEY", "svc-key")
    monkeypatch.setattr(sa.settings, "SUPABASE_PUBLISHABLE_KEY", "anon-key")
    monkeypatch.setattr(sa.httpx, "post", fake_post)

    sa.request_password_reset("user@example.com")
    assert calls["url"].endswith("/auth/v1/recover")
    assert calls["json"] == {"email": "user@example.com"}
