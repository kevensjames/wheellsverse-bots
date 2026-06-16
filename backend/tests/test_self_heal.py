"""self_heal — bounded auto-remediation. Detection is read-only; auto-fix is
triple-gated (scope + approval + KAI_SELF_HEAL_ENABLED) and allowlisted to
safe/reversible actions. Tests isolate .env/logs to tmp dirs — never touch the
real repo."""
from __future__ import annotations

import json
import tempfile
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import self_heal


@pytest.fixture()
def _isolated_audit(monkeypatch):
    """Isolate the governance audit log so denied/destructive paths (which
    record) don't pollute the real audit.jsonl."""
    from app.services.governance import audit_log as _al
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        yield


@pytest.fixture()
def env_and_logs(tmp_path, monkeypatch):
    """Point self_heal at a throwaway .env + logs dir."""
    env = tmp_path / ".env"
    env.write_text('OLLAMA_MODEL_MAP={"gpt-4o":"qwen2.5:7b"}\nOTHER=1\n')
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(self_heal, "_ENV", env)
    monkeypatch.setattr(self_heal, "_LOGS", logs)
    monkeypatch.setattr(self_heal, "_REPO", tmp_path)
    return env, logs


# ─── detection ───────────────────────────────────────────────────────


def test_detect_model_map_gap(env_and_logs):
    env, logs = env_and_logs
    (logs / "104_finance_agent.log").write_text(
        "ERROR model 'claude-haiku-4-5-20251001' not found\n"
        "ERROR model 'claude-haiku-4-5-20251001' not found\n"
        "ERROR model 'gpt-4o' not found\n"  # gpt-4o IS mapped → not a gap
    )
    issues = self_heal.detect()
    gap = next(i for i in issues if i["kind"] == "model_map_gap")
    assert "claude-haiku-4-5-20251001" in gap["models"]
    assert "gpt-4o" not in gap["models"]  # already mapped
    assert gap["auto_fixable"] is True


def test_detect_disk_pressure(env_and_logs, monkeypatch):
    monkeypatch.setattr(self_heal.shutil, "disk_usage",
                        lambda p: SimpleNamespace(total=100, used=92, free=8))
    assert any(i["kind"] == "disk" for i in self_heal.detect())


def test_detect_clean_system(env_and_logs, monkeypatch):
    monkeypatch.setattr(self_heal.shutil, "disk_usage",
                        lambda p: SimpleNamespace(total=100, used=10, free=90))
    assert self_heal.detect() == []  # no logs errors, disk fine


# ─── the model-map fixer (safe + reversible) ─────────────────────────


def test_fix_model_map_adds_only_missing(env_and_logs):
    env, _ = env_and_logs
    res = self_heal._fix_model_map_gap(["claude-haiku-9", "gpt-4o"])
    assert res["ok"] and "claude-haiku-9" in res["added"]
    assert "gpt-4o" not in res["added"]  # never re-maps existing
    m = json.loads(next(l for l in env.read_text().splitlines()
                         if l.startswith("OLLAMA_MODEL_MAP=")).split("=", 1)[1])
    assert m["claude-haiku-9"] == "llama3.2:latest"  # haiku → light model
    assert m["gpt-4o"] == "qwen2.5:7b"               # untouched
    # a backup was written (reversible)
    assert res["backup"] and "selfheal" in res["backup"]


def test_fix_model_map_heavy_model_picks_qwen(env_and_logs):
    res = self_heal._fix_model_map_gap(["claude-sonnet-9"])
    assert res["added"]["claude-sonnet-9"] == "qwen2.5:7b"


# ─── heal() orchestration + gating ───────────────────────────────────


def test_heal_dryrun_changes_nothing(env_and_logs):
    env, logs = env_and_logs
    (logs / "x.log").write_text("model 'claude-zzz' not found\n")
    before = env.read_text()
    rep = self_heal.heal(apply=False)
    assert rep["applied"] == [] and rep["detected"]
    assert env.read_text() == before  # untouched


def test_heal_apply_blocked_without_kill_switch(env_and_logs, monkeypatch):
    monkeypatch.delenv("KAI_SELF_HEAL_ENABLED", raising=False)
    (env_and_logs[1] / "x.log").write_text("model 'claude-zzz' not found\n")
    rep = self_heal.heal(apply=True)
    assert rep["skipped_disabled"] is True and rep["applied"] == []


def test_heal_apply_fixes_when_enabled(env_and_logs, monkeypatch):
    env, logs = env_and_logs
    monkeypatch.setenv("KAI_SELF_HEAL_ENABLED", "1")
    (logs / "x.log").write_text("model 'claude-zzz' not found\n")
    rep = self_heal.heal(apply=True)
    kinds = [a["kind"] for a in rep["applied"]]
    assert "model_map_gap" in kinds
    m = json.loads(next(l for l in env.read_text().splitlines()
                        if l.startswith("OLLAMA_MODEL_MAP=")).split("=", 1)[1])
    assert "claude-zzz" in m  # actually written


# ─── endpoint gating (governance) ────────────────────────────────────

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


def test_endpoint_dryrun_is_open(client, monkeypatch):
    monkeypatch.setattr(self_heal, "heal", lambda apply: {"detected": [], "applied": [], "dry": not apply})
    r = client.post("/admin/self-heal/run", headers=ADMIN_HEADERS, json={"apply": False})
    assert r.status_code == 200 and r.json()["dry"] is True


def test_endpoint_apply_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_SELF_HEAL", raising=False)
    monkeypatch.delenv("KAI_SCOPE_SELF", raising=False)
    r = client.post("/admin/self-heal/run", headers=ADMIN_HEADERS, json={"apply": True})
    assert r.status_code == 403


def test_endpoint_apply_needs_approval_409(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_SELF_HEAL", "1")
    r = client.post("/admin/self-heal/run", headers=ADMIN_HEADERS,
                    json={"apply": True, "approved": False})
    assert r.status_code == 409


def test_endpoint_apply_approved_runs(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_SELF_HEAL", "1")
    monkeypatch.setattr(self_heal, "heal", lambda apply: {"applied": [{"kind": "disk"}], "ok": True})
    r = client.post("/admin/self-heal/run", headers=ADMIN_HEADERS,
                    json={"apply": True, "approved": True})
    assert r.status_code == 200 and r.json()["ok"] is True
