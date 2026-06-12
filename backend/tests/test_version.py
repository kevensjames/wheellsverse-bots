"""GET /version exposes a `build` stamp (admin.js mtime) so the dashboard can
detect a newer deploy and offer a one-click reload. Must stay monitor-safe:
name/version preserved, build is an int.
"""
from __future__ import annotations


def test_version_includes_build(client):
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body.get("name")
    assert body.get("version") == "0.1.0"
    assert isinstance(body.get("build"), int)
    assert body["build"] >= 0


def test_dashboard_build_matches_admin_js_mtime():
    # The build stamp must equal admin.js's mtime — the same number the
    # stamper bakes into ?v=ts-<mtime> — or the client comparison is bogus.
    from pathlib import Path

    from app.main import _dashboard_build

    p = Path(__file__).resolve().parents[1] / "app" / "static" / "nai" / "admin.js"
    assert _dashboard_build() == int(p.stat().st_mtime)
