"""Autonomous-agent endpoints: create+plan, Gate 1 (approval + scope), transitions.

Admin auth and the sandbox runtime are overridden so these test SWE GOVERNANCE
(scopes, approval, state machine) — not admin-token env or Docker."""
import pytest

from app.dependencies.admin import require_admin_token
from app.dependencies.approver import require_approver
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
    app.dependency_overrides[require_approver] = lambda: "op@kai"
    yield {"src": str(src)}
    app.dependency_overrides.pop(require_admin_token, None)
    app.dependency_overrides.pop(require_approver, None)


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


def test_gate1_requires_approver_token(client, swe_env):
    # Identity comes from X-Approver-Token, not the body — no token, no approval.
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    app.dependency_overrides.pop(require_approver, None)
    r = client.post("/admin/swe/tasks/t1/plan/approve", json={"approved": True})
    assert r.status_code == 403
    assert fake.calls == []


def test_approver_identity_is_not_self_declared(client, swe_env):
    # A body-supplied "approver" must be ignored; the audit records the token's
    # identity (op@kai from the fixture override), not the caller's claim.
    fake = _fake_success(); _install(fake)
    _create(client, swe_env["src"])
    r = client.post("/admin/swe/tasks/t1/plan/approve",
                    json={"approved": True, "approver": "somebody-else"})
    assert r.status_code == 200
    assert r.json()["plan_approved_by"] == "op@kai"


def test_require_approver_resolves_token_to_admin_user(db_session):
    import hashlib
    import uuid as _uuid
    from fastapi import HTTPException
    from sqlalchemy import text as _text
    from app.dependencies.approver import require_approver as _dep

    tok = "s3cret-approver-token"
    email = f"a-{_uuid.uuid4().hex[:8]}@kai"
    db_session.execute(
        _text("INSERT INTO admin_users (email, password_hash, role) "
              "VALUES (:e, :h, 'approver')"),
        {"e": email, "h": hashlib.sha256(tok.encode()).hexdigest()},
    )
    db_session.commit()
    assert _dep(x_approver_token=tok, db=db_session) == email
    for bad in (None, "wrong-token"):
        with pytest.raises(HTTPException) as ei:
            _dep(x_approver_token=bad, db=db_session)
        assert ei.value.status_code == 403

    # A non-approver row with the SAME hash must NOT be accepted (role filter).
    other = f"b-{_uuid.uuid4().hex[:8]}@kai"
    db_session.execute(
        _text("INSERT INTO admin_users (email, password_hash, role) VALUES (:e, :h, 'admin')"),
        {"e": other, "h": hashlib.sha256(b"admin-only-token").hexdigest()},
    )
    db_session.commit()
    with pytest.raises(HTTPException) as ei:
        _dep(x_approver_token="admin-only-token", db=db_session)
    assert ei.value.status_code == 403


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


# ── Gate 2 (push/approve) — governance only; push.apply_and_push is stubbed ───
def _to_push_ready(client, swe_env):
    _install(_fake_success())
    _create(client, swe_env["src"])
    client.post("/admin/swe/tasks/t1/plan/approve", json={"approved": True, "approver": "op"})
    # task is now awaiting_push_approval with a real patch + patch_sha256


def _stub_push(monkeypatch, sink=None):
    def fake(**k):
        if sink is not None:
            sink.append(k)
        return {"review_branch": "kai/swe/t1", "remote": "example", "commit": "abc123"}
    monkeypatch.setattr("app.routers.admin_swe_tasks.push.apply_and_push", fake)


def test_gate2_unapproved_does_not_push(client, swe_env, monkeypatch):
    _to_push_ready(client, swe_env)
    calls = []
    _stub_push(monkeypatch, calls)
    # scope ON so the approval gate (not the scope gate) is what refuses.
    monkeypatch.setenv("KAI_SCOPE_SWEPUSH_EXECUTE", "1")
    r = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": False, "approver": "op"})
    assert r.status_code == 409                              # PendingApproval
    assert calls == []                                       # no push without approval
    assert client.get("/admin/swe/tasks/t1").json()["status"] == "awaiting_push_approval"


def test_gate2_requires_swepush_scope(client, swe_env, monkeypatch):
    _to_push_ready(client, swe_env)
    _stub_push(monkeypatch)
    # swe_env grants swe.plan + swe.brain.execute, NOT swepush.execute
    r = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": True, "approver": "op"})
    assert r.status_code == 403


def test_gate2_swe_wildcard_does_not_grant_push(client, swe_env, monkeypatch):
    _to_push_ready(client, swe_env)
    _stub_push(monkeypatch)
    monkeypatch.setenv("KAI_SCOPE_SWE", "1")                 # module wildcard
    r = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": True, "approver": "op"})
    assert r.status_code == 403                              # SWEPUSH root is disjoint


def test_gate2_approved_pushes(client, swe_env, monkeypatch):
    _to_push_ready(client, swe_env)
    monkeypatch.setenv("KAI_SCOPE_SWEPUSH_EXECUTE", "1")
    seen = []
    _stub_push(monkeypatch, seen)
    r = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": True, "approver": "op@kai"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pushed"
    assert body["push_approved_by"] == "op@kai" and body["review_branch"] == "kai/swe/t1"
    assert len(seen) == 1 and seen[0]["task_id"] == "t1"


def test_gate2_patch_sha_mismatch_blocks_push(client, swe_env, monkeypatch, db_session):
    _to_push_ready(client, swe_env)
    monkeypatch.setenv("KAI_SCOPE_SWEPUSH_EXECUTE", "1")
    calls = []
    _stub_push(monkeypatch, calls)
    # tamper the patch after Gate-1 review → stored sha256 no longer matches
    from sqlalchemy import text
    db_session.execute(text("UPDATE kai_swe_tasks SET patch='TAMPERED' WHERE task_id='t1'"))
    db_session.commit()
    r = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": True, "approver": "op"})
    assert r.status_code == 400                              # sha256 mismatch
    assert calls == []                                       # never pushed the swapped patch


def test_two_person_control_blocks_same_approver(client, swe_env, monkeypatch):
    _to_push_ready(client, swe_env)          # plan approved by op@kai
    monkeypatch.setenv("KAI_SCOPE_SWEPUSH_EXECUTE", "1")
    monkeypatch.setenv("KAI_SWE_REQUIRE_TWO_PERSON", "1")
    calls = []
    _stub_push(monkeypatch, calls)
    # same identity approving the push → refused
    r = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": True})
    assert r.status_code == 403 and calls == []
    # a DIFFERENT approver → allowed
    app.dependency_overrides[require_approver] = lambda: "second@kai"
    r2 = client.post("/admin/swe/tasks/t1/push/approve", json={"approved": True})
    assert r2.status_code == 200, r2.text
    assert r2.json()["push_approved_by"] == "second@kai" and len(calls) == 1


def test_reject_unsticks_stranded_pushing(client, swe_env, db_session):
    # A hard kill mid-push leaves the row 'pushing'; reject() is the un-stick.
    from app.services.swe_runtime import task_store
    _to_push_ready(client, swe_env)
    task_store.transition(db_session, task_id="t1",
                          from_status="awaiting_push_approval", to_status="pushing")
    r = client.post("/admin/swe/tasks/t1/reject", json={"approved": False, "approver": "op"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
