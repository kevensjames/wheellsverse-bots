"""Autonomous-agent endpoints: create+plan, Gate 1 (approval + scope), transitions.

Admin auth and the sandbox runtime are overridden so these test SWE GOVERNANCE
(scopes, approval, state machine) — not admin-token env or Docker."""
import pytest

from app.dependencies.admin import require_admin_token
from app.main import app
from app.routers.admin_swe_tasks import get_swe_runtime
from app.services.swe_runtime.sandbox import SandboxResult


class FakeRuntime:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_task(self, task):
        self.calls.append(task)
        return self.result


def _fake_success():
    return FakeRuntime(SandboxResult(
        0, "", "", artifacts={"lib.py": "def add(a, b):\n    return a + b\n"}))


def _install(fake):
    app.dependency_overrides[get_swe_runtime] = lambda: fake


@pytest.fixture
def swe_env(monkeypatch, tmp_path):
    src = tmp_path / "repo"
    src.mkdir()
    (src / "lib.py").write_text("def add(a, b):\n    return a - b\n")
    monkeypatch.setenv("KAI_SWE_RUNTIME_ENABLED", "1")
    monkeypatch.setenv("KAI_SWE_REPO_ALLOWLIST", str(src))
    monkeypatch.setenv("KAI_SCOPE_SWE_PLAN", "1")
    monkeypatch.setenv("KAI_SCOPE_SWE_BRAIN_EXECUTE", "1")
    app.dependency_overrides[require_admin_token] = lambda: None
    yield {"src": str(src)}
    app.dependency_overrides.pop(require_admin_token, None)


def _create(client, src, commands=("sed -i 's/a - b/a + b/' lib.py",), task_id="t1"):
    return client.post("/admin/swe/tasks", json={
        "goal": "fix add", "source_dir": src, "commands": list(commands), "task_id": task_id,
    })


def test_create_produces_plan(client, swe_env):
    r = _create(client, swe_env["src"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_plan_approval"
    assert len(body["plan"]) == 1 and body["plan"][0]["command"].startswith("sed")


def test_create_requires_scope(client, swe_env, monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_SWE_PLAN", raising=False)
    assert _create(client, swe_env["src"]).status_code == 403


def test_create_runtime_disabled(client, swe_env, monkeypatch):
    monkeypatch.setenv("KAI_SWE_RUNTIME_ENABLED", "0")
    assert _create(client, swe_env["src"]).status_code == 409


def test_create_source_not_allowlisted(client, swe_env, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    r = client.post("/admin/swe/tasks",
                    json={"goal": "x", "source_dir": str(other), "commands": ["true"]})
    assert r.status_code == 403


def test_create_requires_commands(client, swe_env):
    r = client.post("/admin/swe/tasks",
                    json={"goal": "x", "source_dir": swe_env["src"], "commands": []})
    assert r.status_code == 400


def test_gate1_unapproved_does_not_execute(client, swe_env):
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    r = client.post("/admin/swe/tasks/t1/plan/approve",
                    json={"approved": False, "approver": "op"})
    assert r.status_code == 409                          # PendingApproval
    assert fake.calls == []                              # SEC-C3: no exec without approval
    assert client.get("/admin/swe/tasks/t1").json()["status"] == "awaiting_plan_approval"


def test_gate1_requires_execute_scope(client, swe_env, monkeypatch):
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    monkeypatch.delenv("KAI_SCOPE_SWE_BRAIN_EXECUTE", raising=False)
    r = client.post("/admin/swe/tasks/t1/plan/approve",
                    json={"approved": True, "approver": "op"})
    assert r.status_code == 403
    assert fake.calls == []


def test_gate1_missing_approver(client, swe_env):
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    r = client.post("/admin/swe/tasks/t1/plan/approve",
                    json={"approved": True, "approver": "  "})
    assert r.status_code == 400


def test_gate1_approved_runs_and_produces_patch(client, swe_env):
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    r = client.post("/admin/swe/tasks/t1/plan/approve",
                    json={"approved": True, "approver": "op@kai"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_push_approval"
    assert body["plan_approved_by"] == "op@kai"
    assert len(fake.calls) == 1
    patch = client.get("/admin/swe/tasks/t1/patch").json()
    assert "a + b" in patch["patch"] and patch["patch_sha256"]


def test_double_approve_blocked(client, swe_env):
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    client.post("/admin/swe/tasks/t1/plan/approve", json={"approved": True, "approver": "op"})
    r2 = client.post("/admin/swe/tasks/t1/plan/approve", json={"approved": True, "approver": "op"})
    assert r2.status_code == 409                          # already advanced


def test_reject(client, swe_env):
    _create(client, swe_env["src"])
    r = client.post("/admin/swe/tasks/t1/reject", json={"approved": False, "approver": "op"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_unknown_task_404(client, swe_env):
    assert client.get("/admin/swe/tasks/nope").status_code == 404


def test_execute_crash_marks_failed_not_stranded(client, swe_env):
    # A raise from the runtime (bug / hard error) must not strand the row in
    # transient 'executing' — the guard moves it to terminal 'failed'.
    class Boom:
        def run_task(self, task):
            raise RuntimeError("kaboom")
    _install(Boom())
    _create(client, swe_env["src"])
    r = client.post("/admin/swe/tasks/t1/plan/approve",
                    json={"approved": True, "approver": "op"})
    assert r.status_code == 503
    assert client.get("/admin/swe/tasks/t1").json()["status"] == "failed"


def test_reject_unsticks_stranded_executing(client, swe_env, db_session):
    # Simulate a crash-strand (a hard kill mid-run leaves the row 'executing'),
    # then confirm reject() is the operator un-stick path.
    from app.services.swe_runtime import task_store
    _create(client, swe_env["src"])
    task_store.transition(db_session, task_id="t1",
                          from_status="awaiting_plan_approval", to_status="executing")
    r = client.post("/admin/swe/tasks/t1/reject", json={"approved": False, "approver": "op"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
