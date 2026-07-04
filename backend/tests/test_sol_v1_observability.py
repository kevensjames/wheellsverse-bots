"""Stage 16 tests — Sol v1 observability (health + Prometheus metrics).

Authz: both endpoints are admin-token gated. Shape: /health reports db_ok +
scheduler arm-state + counts; /metrics returns Prometheus text-exposition format.
Read-only, NON-CUSTODIAL.
"""
from __future__ import annotations

from app.config import settings

ADMIN = {"X-Admin-Token": settings.admin_token}


def test_health_and_metrics_require_admin_token(client):
    assert client.get("/admin/sol-v1/health").status_code == 403
    assert client.get("/admin/sol-v1/metrics").status_code == 403


def test_health_shape_with_token(client):
    r = client.get("/admin/sol-v1/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["db_ok"] is True and body["status"] == "ok"
    # scheduler arm-state surfaced (both off by default in tests)
    assert set(body["schedulers"]) == {"reminders", "supervisor"}
    for s in body["schedulers"].values():
        assert set(s) == {"enabled", "running", "hour_utc"}
    assert set(body["counts"]) == {"groups", "memberships", "cycles", "payments"}


def test_metrics_prometheus_format_with_token(client):
    r = client.get("/admin/sol-v1/metrics", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    # exposition format: HELP/TYPE comments + sol_-prefixed metric lines
    assert "# TYPE sol_groups gauge" in body
    assert 'sol_groups{status="open"}' in body
    assert 'sol_payments{status="confirmed"}' in body
    assert 'sol_attention{kind="overdue"}' in body
    assert "sol_members_total" in body
    # every non-comment line is a sol_ metric
    for line in body.strip().splitlines():
        assert line.startswith("#") or line.startswith("sol_"), line


def test_metrics_endpoint_registered():
    from app.routers.sol_v1_admin import router

    paths = {r.path for r in router.routes}
    assert "/admin/sol-v1/health" in paths and "/admin/sol-v1/metrics" in paths
