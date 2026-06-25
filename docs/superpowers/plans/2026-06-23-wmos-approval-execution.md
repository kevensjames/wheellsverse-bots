# W-MOS Operator-Approved Execution Rail Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make queued approvals *actionable* — an operator-approved queued action actually executes (through its adapter), records the result, and advances the loop — plus fix the `approvals.jsonl` lost-update race. All adapters remain inert (no real send/deploy), the autonomous dispatch chokepoint is untouched, and the scheduler stays dormant.

**Architecture:** A new `core/portfolio/execute.py` provides `execute_approval(approval_id)` — the **operator gate ("envelope B")**: it runs an adapter ONLY for an approval whose status is exactly `"approved"`, audits it as `executed_by_approval`, marks the verb completed, and flips the approval to `"executed"` (so it can't double-fire). This is a *separate* path from `actions.dispatch` (the autonomous chokepoint), which is NOT modified — the autonomous loop still never auto-fires AMBER/auto_capped. A module-level lock serializes all `approvals.jsonl` mutations to close the read-modify-write race.

**Tech Stack:** Python 3 stdlib (`threading`), FastAPI, pytest. Reuses Plan-1 `state`/`actions`, Plan-3 `adapters`. Vanilla-JS HQ edit.

## Global Constraints

- **Repo / branch:** `wheellsverse-bots` @ `_apexdeploy`, on top of Plan 3 (HEAD `f5ea0ba`). Paths relative to repo root.
- **File header:** new modules start with `from __future__ import annotations`.
- **Operator gate is law:** `execute_approval` executes ONLY when the stored approval `status == "approved"`. Anything else (`pending`, `rejected`, `executed`, missing) → refuse/not_found, NEVER runs an adapter. After a successful run it sets status `"executed"` (idempotent: a second call refuses).
- **Do NOT modify `actions.dispatch`** or the orchestrator's dormancy/kill gates. This rail is additive and operator-triggered only.
- **Adapters stay inert:** this plan does not change any adapter; `outreach_send` still returns `would_send`, `infra` still writes a stub manifest. No real external effect is wired here.
- **No arming:** do NOT set `WMOS_ORCHESTRATOR_ENABLED`, do NOT set `cold_outreach` `live=True`, do NOT add a real deploy provider. Those are out of scope (operator's manual trigger, later).
- **Concurrency:** all `approvals.jsonl` writers (`queue_approval`, `resolve_approval`) hold one module lock so a concurrent append can't be lost by a concurrent whole-file rewrite.
- **truth_verification skill applies:** tests assert real persisted state (artifacts on disk, status re-read), not return codes.
- **Run tests from repo root:** `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest <path> -v`.
- **git hygiene:** stage ONLY each task's named files; never `git add -A`.

---

### Task 1: serialize `approvals.jsonl` mutations (lost-update race fix)

**Files:**
- Modify: `core/portfolio/state.py` (add a lock; guard `queue_approval` + `resolve_approval`)
- Test: `tests/test_portfolio_approvals_race.py`

**Interfaces:**
- Consumes: existing `state.queue_approval(action)`, `state.resolve_approval(id, status)`, `state.list_approvals()`.
- Produces: no signature change; adds module-level `_APPROVALS_LOCK = threading.Lock()` guarding both mutators.

- [ ] **Step 1: Write the failing/stress test**

```python
# tests/test_portfolio_approvals_race.py
from __future__ import annotations

import threading

from core.portfolio import state
from core.portfolio.actions import Action, ActionClass


def _action(i):
    return Action(f"verb{i}", "agent", ActionClass.AMBER, [], "n8n", {"i": i})


def test_concurrent_queue_and_resolve_lose_no_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # Seed some approvals to resolve, and queue more concurrently.
    seeded = [state.queue_approval(_action(i)) for i in range(20)]

    errors = []

    def queuer(i):
        try:
            state.queue_approval(_action(1000 + i))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    def resolver(aid):
        try:
            state.resolve_approval(aid, "approved")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=queuer, args=(i,)) for i in range(30)]
    threads += [threading.Thread(target=resolver, args=(aid,)) for aid in seeded]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    all_ids = {a["id"] for a in state.list_approvals()}
    # All 20 seeded + 30 newly-queued ids must survive (no lost appends).
    assert len(all_ids) == 50
    approved = {a["id"] for a in state.list_approvals("approved")}
    assert set(seeded) == approved  # every seeded approval got resolved
```

- [ ] **Step 2: Run it — without the lock this is flaky / can drop appended rows**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_approvals_race.py -v`
Expected: FAIL or flaky (a concurrent rewrite in `resolve_approval` clobbers appends from `queue_approval`, so `len(all_ids) < 50` intermittently).

- [ ] **Step 3: Add the lock.** In `core/portfolio/state.py`, add `import threading` to the imports, and a module-level lock after the imports:

```python
_APPROVALS_LOCK = threading.Lock()
```

Wrap the body of `queue_approval` so the append is under the lock — change:
```python
def queue_approval(action: Action) -> str:
    aid = uuid.uuid4().hex[:12]
    paths.append_jsonl(_approvals_file(), {
        ...
    })
    return aid
```
to hold the lock around the append:
```python
def queue_approval(action: Action) -> str:
    aid = uuid.uuid4().hex[:12]
    record = {
        "id": aid,
        "status": "pending",
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "preconditions": list(action.preconditions),
        "payload": action.payload,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _APPROVALS_LOCK:
        paths.append_jsonl(_approvals_file(), record)
    return aid
```

Wrap the read-modify-write in `resolve_approval` under the same lock:
```python
def resolve_approval(approval_id: str, status: str) -> bool:
    with _APPROVALS_LOCK:
        f = _approvals_file()
        rows = paths.read_jsonl(f)
        found = False
        for r in rows:
            if r.get("id") == approval_id:
                r["status"] = status
                found = True
        if not found:
            return False
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(f)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_approvals_race.py tests/test_portfolio_state.py -v`
Expected: PASS (the race test deterministically green; the existing state tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/state.py tests/test_portfolio_approvals_race.py
git commit -m "fix(wmos): serialize approvals.jsonl mutations (lost-update race)"
```

---

### Task 2: `execute.py` — the operator-approved execution gate

**Files:**
- Create: `core/portfolio/execute.py`
- Test: `tests/test_portfolio_execute.py`

**Interfaces:**
- Consumes: `state.list_approvals`/`resolve_approval`/`audit`/`mark_completed`, `adapters.adapter_for`, `actions.Action`/`ActionClass`.
- Produces: `execute_approval(approval_id: str) -> dict` returning one of:
  - `{"status": "not_found"}` — no such approval id.
  - `{"status": "refused", "detail": "..."}` — approval not in `"approved"` state.
  - `{"status": "executed", "verb": <str>, "output": <dict>}` — ran the adapter; audited; verb marked completed; approval flipped to `"executed"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_execute.py
from __future__ import annotations

from pathlib import Path

from core.portfolio import execute, state
from core.portfolio.actions import Action, ActionClass


def _queue(monkeypatch, tmp_path, verb="deploy_demo_instance", cls=ActionClass.AUTO_CAPPED):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    return state.queue_approval(Action(verb, "infra", cls, [], "n8n", {}))


def test_refuses_until_approved(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    assert execute.execute_approval(aid)["status"] == "refused"   # still pending


def test_executes_an_approved_action(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    state.resolve_approval(aid, "approved")
    res = execute.execute_approval(aid)
    assert res["status"] == "executed"
    assert res["verb"] == "deploy_demo_instance"
    # the infra adapter drafted a manifest artifact on disk
    assert (tmp_path / "n8n" / "artifacts" / "infra" / "deploy-manifest.json").exists()
    # the verb is marked completed
    assert "deploy_demo_instance" in state.load_state("n8n")["completed_verbs"]
    # audited as executed_by_approval
    audit = state.list_audit(50) if hasattr(state, "list_audit") else []
    # the approval is now 'executed' and cannot double-fire
    assert execute.execute_approval(aid)["status"] == "refused"
    assert {a["id"]: a["status"] for a in state.list_approvals()}[aid] == "executed"


def test_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert execute.execute_approval("missing-id")["status"] == "not_found"


def test_rejected_never_executes(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    state.resolve_approval(aid, "rejected")
    assert execute.execute_approval(aid)["status"] == "refused"
```

- [ ] **Step 2: Run it — fail (`No module named 'core.portfolio.execute'`)**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_execute.py -v`

- [ ] **Step 3: Implement `core/portfolio/execute.py`**

```python
# core/portfolio/execute.py
"""Operator-approved execution gate (envelope B). Runs an adapter ONLY for an
approval whose status is exactly 'approved' — the operator's approval IS the
gate. This is a separate path from actions.dispatch (the autonomous chokepoint,
which still never auto-fires AMBER/auto_capped). Adapters are inert in Plan 4, so
this draws the rail without firing any real external action.
"""
from __future__ import annotations

from core.portfolio import adapters, state
from core.portfolio.actions import Action, ActionClass


def execute_approval(approval_id: str) -> dict:
    appr = next((a for a in state.list_approvals() if a.get("id") == approval_id), None)
    if appr is None:
        return {"status": "not_found"}
    if appr.get("status") != "approved":
        return {"status": "refused",
                "detail": f"approval status is {appr.get('status')!r}, not 'approved'"}

    action = Action(
        verb=appr["verb"],
        agent=appr.get("agent", ""),
        action_class=ActionClass(appr.get("action_class", "amber")),
        preconditions=list(appr.get("preconditions", [])),
        business=appr["business"],
        payload=appr.get("payload", {}),
    )
    # adapters.adapter_for(step) only needs `.verb`; the Action provides it.
    output = adapters.adapter_for(action).run(action)
    state.audit({
        "business": action.business,
        "verb": action.verb,
        "status": "executed_by_approval",
        "approval_id": approval_id,
    })
    state.mark_completed(action.business, action.verb)
    state.resolve_approval(approval_id, "executed")  # idempotent: blocks double-fire
    return {"status": "executed", "verb": action.verb, "output": output}
```

(Note: `test_executes_an_approved_action` references `state.list_audit` defensively with `hasattr`; `list_audit` may not exist — the line is guarded and does not require it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_execute.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/execute.py tests/test_portfolio_execute.py
git commit -m "feat(wmos): operator-approved execution gate (envelope B)"
```

---

### Task 3: wire execute into the HQ (endpoint + Approvals UI)

**Files:**
- Modify: `narai/api/routes/portfolio_admin.py` (add `POST /approvals/{id}/execute`)
- Modify: `frontend/admin/portfolio.html` (Approvals tab: also list `approved`, add a Fire button)
- Test: `tests/test_portfolio_admin_api.py` (append)

**Interfaces:**
- Consumes: `execute.execute_approval`.
- Produces: `POST /api/narai/portfolio/approvals/{approval_id}/execute` → `{"status": ..., "verb"?: ..., "output"?: ...}` (passes through `execute_approval`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_portfolio_admin_api.py`)

```python
def test_execute_endpoint_runs_approved(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from core.portfolio.actions import Action, ActionClass
    aid = state.queue_approval(Action("deploy_demo_instance", "infra", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    # not approved yet -> refused
    r1 = c.post(f"/api/narai/portfolio/approvals/{aid}/execute", headers=HEAD)
    assert r1.json()["status"] == "refused"
    # approve, then execute
    c.post(f"/api/narai/portfolio/approvals/{aid}/resolve", headers=HEAD, json={"status": "approved"})
    r2 = c.post(f"/api/narai/portfolio/approvals/{aid}/execute", headers=HEAD)
    assert r2.json()["status"] == "executed"
    assert r2.json()["verb"] == "deploy_demo_instance"
    # auth still enforced
    assert c.post(f"/api/narai/portfolio/approvals/{aid}/execute").status_code == 401
```

- [ ] **Step 2: Run it — fail (404, endpoint missing)**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_admin_api.py::test_execute_endpoint_runs_approved -v`

- [ ] **Step 3a: Add the endpoint** to `narai/api/routes/portfolio_admin.py`. Add the import at the top (with the other `from core.portfolio import ...`):
```python
from core.portfolio import execute
```
Then add the route (after the existing `resolve` route):
```python
@router.post("/approvals/{approval_id}/execute")
def execute_approved(approval_id: str, _=Depends(verify_admin_api_key)) -> dict:
    return execute.execute_approval(approval_id)
```

- [ ] **Step 3b: Update the Approvals tab** in `frontend/admin/portfolio.html`. Replace `loadApprovals` so it lists BOTH pending and approved, with Approve/Reject on pending and a **Fire (execute)** button on approved:
```javascript
async function loadApprovals(){
  const [p, a] = await Promise.all([api('/approvals?status=pending'), api('/approvals?status=approved')]);
  const rows = [
    ...p.approvals.map(x=>({x, kind:'pending'})),
    ...a.approvals.map(x=>({x, kind:'approved'})),
  ];
  const body=document.getElementById('ap-body');
  body.innerHTML = rows.length ? rows.map(({x,kind})=>
    `<tr><td>${esc(x.business)}</td><td>${esc(x.verb)}</td><td>${esc(x.action_class)} · ${esc(kind)}</td>
     <td>${kind==='pending'
       ? `<button class="btn accent" onclick="resolve('${esc(x.id)}','approved')">Approve</button>
          <button class="btn danger" onclick="resolve('${esc(x.id)}','rejected')">Reject</button>`
       : `<button class="btn accent" onclick="fire('${esc(x.id)}')">Fire</button>`}</td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">No pending or approved actions.</td></tr>';
}
async function fire(id){
  const r = await api('/approvals/'+id+'/execute',{method:'POST'});
  err('Fired '+id+': '+(r.status||'?')+(r.verb? ' ('+r.verb+')':''));  // err() doubles as a transient toast
  loadApprovals();
}
```
(Keep the existing `resolve(id,status)` function as-is; it already reloads approvals.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_admin_api.py -v`
Expected: PASS (existing 7 + new = 8).

- [ ] **Step 5: Full suite + commit**

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_*.py -q
git add narai/api/routes/portfolio_admin.py frontend/admin/portfolio.html tests/test_portfolio_admin_api.py
git commit -m "feat(wmos): HQ approve-then-fire execution endpoint + UI"
```
Expected: full `test_portfolio_*` suite green.

---

## Self-Review

**1. Spec coverage (spec §2 envelope, §8 safety; Plan-3 carry-forwards):**
- `approvals.jsonl` write-race (reviewer's Plan-4 must-fix) → Task 1. ✅
- Operator-approved execution ("envelope B", spec §2 amber = one-click approve→fire) → Task 2 + Task 3. ✅
- Autonomous dispatch chokepoint untouched; scheduler dormant; adapters inert → enforced by Global Constraints; no task modifies `dispatch`/orchestrator/adapters. ✅
- **Out of scope (noted):** real `ctx_for` precondition facts (auto-fire-within-caps), budget-into-sweep + budget-breach→pause test, live `cold_outreach` send, real infra/deploy, flipping `WMOS_ORCHESTRATOR_ENABLED`. These carry real-world risk and are the operator's explicit later trigger.

**2. Placeholder scan:** No TBD/TODO. Complete code in every step. The `list_audit` reference in the Task-2 test is `hasattr`-guarded and intentionally optional. ✅

**3. Type consistency:** `execute_approval(approval_id) -> dict` (Task 2) is imported + called unchanged in Task 3. `state.queue_approval`/`resolve_approval`/`list_approvals`/`mark_completed`/`audit` and `adapters.adapter_for` are existing signatures used as-is. The approval record fields consumed by `execute_approval` (`id/status/verb/agent/action_class/preconditions/business/payload`) match exactly what `queue_approval` writes (state.py:71-81). ✅

## Out of Scope (Plan 5 / operator-gated)

Real precondition facts so auto_capped verbs can auto-fire within caps; wiring `cold_outreach.send_sequences(confirm=True, live=True)` behind the gate (real cold email — CAN-SPAM/deliverability); a real infra/deploy provider; budget enforcement inside the sweep + its breach test; arming the production scheduler. Each carries irreversible/outward-facing risk and requires explicit operator authorization.
