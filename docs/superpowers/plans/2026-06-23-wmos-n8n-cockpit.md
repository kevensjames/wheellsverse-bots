# W-MOS n8n Build Cockpit + Adapters Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax. **Task 2 is a PARALLEL fan-out** — its 8 adapters are independent files and may be built concurrently (one agent each); everything else is sequential.

**Goal:** Wire the first per-business **Build Cockpit** (`/admin/portfolio/n8n`) to the Plan-1 engine with real, decoupled adapters, so ticking the n8n loop **drafts artifacts** (research, workflow pack, leads, outreach copy, proposal) via GREEN adapters and **queues** every external action (send/publish/deploy) through the envelope.

**Architecture:** Adapters live in `core/portfolio/adapters/` and each takes an **injected `generate(prompt:str)->str`** callable — so they are pure units with NO dependency on the `backend/app` KAI package and need no LLM mocking (tests inject a stub). A shared `core/portfolio/llm.py` provides the real local-first `generate` used only at the wiring layer. A cockpit router calls `loops.tick(slug, adapter_for, ctx_for)`; `ctx_for` returns all preconditions falsy by default, so auto_capped steps queue (safe). The cockpit HTML is served at `/admin/portfolio/{slug}` and reaches the engine only through this router.

**Tech Stack:** Python 3 / FastAPI, pytest + TestClient, vanilla-JS HTML. Reuses Plan-1 `actions`/`state`/`loops`/`registry`/`paths` and `core/places_scanner.py` + `core/cold_outreach.py` (same `core/` package — safe imports).

## Global Constraints

- **Repo / branch:** `wheellsverse-bots` @ `_apexdeploy`, on top of Plan 2 (HEAD `cac5344`). Paths relative to repo root.
- **File header:** every Python module starts with `from __future__ import annotations`.
- **Adapter contract:** every adapter implements `run(self, action: Action) -> dict` (the Plan-1 `AgentAdapter` Protocol from `core.portfolio.actions`). Generative adapters take `generate` in `__init__` and write a draft via `state.record_artifact(action.business, kind, name, content)`, returning `{"artifact": <str path>, "verb": action.verb, ...}`. Adapters NEVER call the LLM wrapper directly in their own module — only the injected `generate`.
- **Decoupling:** adapters import only from `core.portfolio.*` and (for leads/send) `core.places_scanner` / `core.cold_outreach`. NO `backend.app.*` imports.
- **Safety:** the cockpit `ctx_for` returns preconditions defaulting falsy → auto_capped verbs (run_outreach_campaign, publish_landing_page, deploy_demo_instance) QUEUE, never auto-fire. GREEN verbs draft artifacts. RED none here.
- **Auth:** cockpit router defines its own `verify_admin_api_key` (X-API-Key == env `API_KEY`, `hmac.compare_digest`, 503/401), like `portfolio_admin.py`.
- **Routing:** cockpit API under `/api/narai/portfolio/biz/{slug}/*` (namespaced away from the HQ's own `/api/narai/portfolio/*` endpoints); cockpit HTML at `/admin/portfolio/{slug}`.
- **Mount:** independent top-level `try/except` in `core/api.py` (like the relocated HQ mount), additive only.
- **truth_verification skill applies:** tests assert real persisted artifacts/state, not return codes.
- **Run tests from repo root:** `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest <path> -v`.
- **git hygiene:** stage ONLY each task's named files; never `git add -A`.

---

### Task 1: `llm.py` — local-first `generate` wrapper (shared prereq)

**Files:**
- Create: `core/portfolio/llm.py`
- Test: `tests/test_portfolio_llm.py`

**Interfaces:**
- Produces: `default_generate(prompt: str, *, system: str | None = None, max_tokens: int = 1200) -> str` — wraps `core.base_bot.BaseBot.claude` (local-first via `LLM_BACKEND`); fail-soft returns `""` on any error.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_llm.py
from core.portfolio import llm


def test_default_generate_returns_text(monkeypatch):
    # Patch BaseBot.claude so no network/LLM is touched.
    import core.base_bot as bb
    monkeypatch.setattr(bb.BaseBot, "claude", lambda self, prompt, **kw: "GENERATED:" + prompt[:10])
    out = llm.default_generate("hello world prompt")
    assert out.startswith("GENERATED:")


def test_default_generate_fail_soft(monkeypatch):
    import core.base_bot as bb
    def boom(self, prompt, **kw):
        raise RuntimeError("llm down")
    monkeypatch.setattr(bb.BaseBot, "claude", boom)
    assert llm.default_generate("x") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.llm'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/llm.py
"""Local-first LLM `generate` wrapper for W-MOS adapters. The ONLY place the
engine touches the brain; adapters receive this as an injected callable so they
stay pure + testable. Fail-soft: returns "" rather than raising, so a brain
outage degrades to an empty draft instead of crashing a tick."""
from __future__ import annotations


def default_generate(prompt: str, *, system: str | None = None, max_tokens: int = 1200) -> str:
    try:
        from core.base_bot import BaseBot
        bot = BaseBot()
        text = bot.claude(prompt, system=system or "You are a concise business operator.",
                          max_tokens=max_tokens)
        return (text or "").strip()
    except Exception:
        return ""
```

(If `BaseBot()` requires constructor args, inspect `core/base_bot.py` and pass the minimal required; the test patches `BaseBot.claude` so construction must succeed with no network.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_llm.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/llm.py tests/test_portfolio_llm.py
git commit -m "feat(wmos): local-first generate wrapper for adapters"
```

---

### Task 2: The 8 adapters (PARALLEL fan-out — one agent each)

**Files (each adapter is an independent new file + its own test):**
- Create: `core/portfolio/adapters/__init__.py` (empty package marker — created by whichever agent runs first, or pre-create it)
- Create + Test per adapter (8): see the table. All share the same shape.

**Interfaces (every adapter):** `class <Name>Adapter:` with `def __init__(self, generate=None, **kw)` and `def run(self, action: Action) -> dict`. GREEN adapters call `self._generate(prompt)` then `state.record_artifact(...)`. Consumes `core.portfolio.actions.Action`, `core.portfolio.state`.

**Common test shape** (each adapter test, with its own filename):
```python
# tests/test_portfolio_adapter_<key>.py
from core.portfolio.adapters.<module> import <Name>Adapter
from core.portfolio.actions import Action, ActionClass
from core.portfolio import state


def test_<key>_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = <Name>Adapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("<verb>", "<agent>", ActionClass.GREEN, [], "n8n", {}))
    assert "artifact" in res
    # the artifact file exists and holds the generated content
    from pathlib import Path
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
```

**Adapter table** (verb → module → class → kind/filename → prompt seed):

| key | module (`core/portfolio/adapters/`) | class | verb | kind / file | run() body |
|---|---|---|---|---|---|
| research | `research.py` | `ResearchAdapter` | research_niche | research/`niche.md` | `c=self._generate(f"Research a profitable automation-agency niche for the n8n business '{action.business}'. List target sub-industry, 3 painful manual workflows, ICP, and a one-line wedge.")` → `record_artifact(action.business,"research","niche.md",c)` |
| workflow | `workflow.py` | `WorkflowPackAdapter` | build_workflow_pack | workflows/`pack.md` | prompt: `"Draft 3 n8n workflow blueprints (trigger → nodes → outcome) that solve the niche's painful workflows for {business}."` |
| leads | `leads.py` | `LeadsAdapter` | generate_lead_list | leads/`prospects.json` | wraps `core.places_scanner.scan(location=action.payload.get("location","Boston, MA"), dry_run=True, limit=action.payload.get("limit",25))`; serialize the returned Prospect dataclasses to JSON via `json.dumps([p.__dict__ for p in prospects], default=str)` → record_artifact. (No `generate`.) |
| outreach_draft | `outreach_draft.py` | `OutreachDraftAdapter` | draft_outreach | outreach/`sequence.md` | prompt: `"Write a 3-touch cold-email sequence (Day 0/3/7, subject+body, CAN-SPAM footer) offering n8n automation setup to a prospect in {business}'s niche."` |
| proposal | `proposal.py` | `ProposalAdapter` | draft_proposal | proposals/`proposal.md` | prompt: `"Draft a 1-page proposal + SOW + price for an n8n automation retainer for a prospect of {business}."` |
| outreach_send | `outreach_send.py` | `OutreachSendAdapter` | run_outreach_campaign | — | AUTO_CAPPED. `run()` (only reached if approved) returns `{"status":"would_send","note":"gated send — wire cold_outreach.send_sequences(confirm=True,live=True) on approval","verb":action.verb}`. No artifact. Test asserts the returned status string + that no send is attempted. |
| site | `site.py` | `SiteAdapter` | publish_landing_page | sites/`landing.html` | GREEN-draft on run: prompt `"Generate a single-file landing page (inline CSS) for {business}'s n8n automation service."` → record_artifact kind="sites" name="landing.html". (Drafting is safe; the *publish* is the gated verb, which queues.) |
| infra | `infra.py` | `InfraAdapter` | deploy_demo_instance | infra/`deploy-manifest.json` | AUTO_CAPPED stub. `run()` returns `{"status":"draft","note":"deploy capability greenfield — operator wires Railway/Coolify","verb":action.verb}` and records a draft manifest `json.dumps({"business":action.business,"target":"TBD","teardown":None})`. |

**Per-adapter task contract** (the agent building each adapter does exactly this):
1. Write `tests/test_portfolio_adapter_<key>.py` using the common test shape (adjust verb/agent/class; for outreach_send/infra assert the documented status string instead of an artifact).
2. Run it → fail (module missing).
3. Write `core/portfolio/adapters/<module>` with the class (header `from __future__ import annotations`; `def __init__(self, generate=None): self._generate = generate or (lambda p: "")`; the `run` body from the table).
4. Run the test → pass.
5. Do NOT git-commit (the controller commits all adapters together after the parallel phase, to avoid index races).

- [ ] **Step A: pre-create the package** `core/portfolio/adapters/__init__.py` with `"""W-MOS adapters."""` (controller does this before fan-out).
- [ ] **Step B: build all 8 adapters in parallel** (Workflow / parallel agents), each per its contract above, writing files but NOT committing.
- [ ] **Step C: controller runs the whole adapter suite + commits**

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_adapter_*.py -v
git add core/portfolio/adapters/ tests/test_portfolio_adapter_*.py
git commit -m "feat(wmos): n8n cockpit adapters (research/workflow/leads/outreach/proposal/site/infra)"
```
Expected: 8 adapter tests pass.

---

### Task 3: adapter registry + `ctx_for` + n8n loop seed

**Files:**
- Modify: `core/portfolio/adapters/__init__.py` (add the registry + builders)
- Create: `core/portfolio/seed.py` (writes n8n `loop.json`)
- Test: `tests/test_portfolio_adapter_registry.py`

**Interfaces:**
- Produces in `adapters/__init__.py`:
  - `ADAPTERS: dict[str, object]` — verb → adapter instance (generative ones built with `llm.default_generate`).
  - `adapter_for(step) -> object` — `ADAPTERS.get(step.verb)` or a `NoopAdapter` (returns `{"status":"noop","verb":step.verb}`).
  - `ctx_for(step) -> dict` — returns `{}` (all preconditions falsy → auto_capped queues). (Plan-4 will populate real precondition facts.)
- Produces in `seed.py`: `seed_n8n_loop() -> Path` — writes `business_dir("n8n")/loop.json` with the spec §4 n8n steps (research_niche, build_workflow_pack, generate_lead_list, draft_outreach, run_outreach_campaign[auto_capped], publish_landing_page[auto_capped], deploy_demo_instance[auto_capped], draft_proposal).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_adapter_registry.py
from core.portfolio import adapters, seed, loops, state
from core.portfolio.actions import ActionClass


def test_adapter_for_maps_known_verbs():
    step = loops.LoopStep("research_niche", "kai.research", ActionClass.GREEN, [])
    assert adapters.adapter_for(step).__class__.__name__ == "ResearchAdapter"
    unknown = loops.LoopStep("nope", "x", ActionClass.GREEN, [])
    assert adapters.adapter_for(unknown).run(_mk(unknown))["status"] == "noop"


def test_ctx_for_defaults_falsy():
    step = loops.LoopStep("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED,
                          ["warmup_complete"])
    assert adapters.ctx_for(step) == {}


def test_seed_writes_n8n_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    p = seed.seed_n8n_loop()
    assert p.exists()
    steps = loops.load_loop("n8n")
    verbs = [s.verb for s in steps]
    assert verbs[0] == "research_niche"
    assert "run_outreach_campaign" in verbs
    sends = next(s for s in steps if s.verb == "run_outreach_campaign")
    assert sends.action_class is ActionClass.AUTO_CAPPED


def _mk(step):
    from core.portfolio.actions import Action
    return Action(step.verb, step.agent, step.action_class, step.preconditions, "n8n", {})
```

- [ ] **Step 2: Run → fail** (`adapter_for`/`seed_n8n_loop` undefined).

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_adapter_registry.py -v`

- [ ] **Step 3: Implement.** Append to `core/portfolio/adapters/__init__.py`:

```python
from core.portfolio import llm
from core.portfolio.adapters.research import ResearchAdapter
from core.portfolio.adapters.workflow import WorkflowPackAdapter
from core.portfolio.adapters.leads import LeadsAdapter
from core.portfolio.adapters.outreach_draft import OutreachDraftAdapter
from core.portfolio.adapters.proposal import ProposalAdapter
from core.portfolio.adapters.outreach_send import OutreachSendAdapter
from core.portfolio.adapters.site import SiteAdapter
from core.portfolio.adapters.infra import InfraAdapter


class NoopAdapter:
    def run(self, action) -> dict:
        return {"status": "noop", "verb": action.verb}


_g = llm.default_generate
ADAPTERS: dict[str, object] = {
    "research_niche": ResearchAdapter(generate=_g),
    "build_workflow_pack": WorkflowPackAdapter(generate=_g),
    "generate_lead_list": LeadsAdapter(),
    "draft_outreach": OutreachDraftAdapter(generate=_g),
    "draft_proposal": ProposalAdapter(generate=_g),
    "run_outreach_campaign": OutreachSendAdapter(),
    "publish_landing_page": SiteAdapter(generate=_g),
    "deploy_demo_instance": InfraAdapter(),
}
_NOOP = NoopAdapter()


def adapter_for(step):
    return ADAPTERS.get(step.verb, _NOOP)


def ctx_for(step) -> dict:
    return {}
```

Create `core/portfolio/seed.py`:

```python
# core/portfolio/seed.py
"""Seed supervisor loop.json files. n8n pilot loop per spec §4."""
from __future__ import annotations

from pathlib import Path

from core.portfolio import paths

_N8N_STEPS = [
    {"verb": "research_niche", "agent": "kai.research", "class": "green"},
    {"verb": "build_workflow_pack", "agent": "kai.planning", "class": "green"},
    {"verb": "generate_lead_list", "agent": "places_scanner", "class": "green"},
    {"verb": "draft_outreach", "agent": "cold_outreach", "class": "green"},
    {"verb": "run_outreach_campaign", "agent": "cold_outreach", "class": "auto_capped",
     "preconditions": ["warmup_complete", "campaign_approved_once", "under_daily_cap"]},
    {"verb": "publish_landing_page", "agent": "site_builder", "class": "auto_capped",
     "preconditions": ["page_approved_once", "unpublish_handle"]},
    {"verb": "deploy_demo_instance", "agent": "infra", "class": "auto_capped",
     "preconditions": ["first_of_kind_approved", "under_cost_ceiling", "teardown_handle"]},
    {"verb": "draft_proposal", "agent": "kai.research", "class": "green"},
]


def seed_n8n_loop() -> Path:
    target = paths.business_dir("n8n") / "loop.json"
    paths.save_json_atomic(target, {"business": "n8n", "steps": _N8N_STEPS})
    return target
```

- [ ] **Step 4: Run → pass.** **Step 5: Commit**

```bash
git add core/portfolio/adapters/__init__.py core/portfolio/seed.py tests/test_portfolio_adapter_registry.py
git commit -m "feat(wmos): adapter registry + ctx_for + n8n loop seed"
```

---

### Task 4: cockpit router

**Files:**
- Create: `narai/api/routes/portfolio_cockpit_admin.py`
- Test: `tests/test_portfolio_cockpit_api.py`

**Interfaces:** `router = APIRouter(prefix="/api/narai/portfolio/biz", tags=["portfolio-cockpit"])` with (all `Depends(verify_admin_api_key)`):
- `GET /{slug}/overview` → `{business, phase, steps:[{verb,class,state}], completed, pending}` (from registry + state + loops; `state` per step = completed|pending|next|todo).
- `GET /{slug}/artifacts` → `{artifacts:[{kind,name,path}]}` (walk `business_dir(slug)/artifacts/`).
- `GET /{slug}/audit` → `{audit:[...]}` (rollup.recent_audit filtered to slug).
- `POST /{slug}/tick` → calls `loops.tick(slug, adapters.adapter_for, adapters.ctx_for)`; returns `{status, verb, detail}` from the DispatchResult (or `{status:"idle"}` if None).
- `POST /{slug}/seed` → `seed.seed_n8n_loop()` if slug=="n8n" else 400; returns `{ok:True}`.
- Test approach: isolated `FastAPI()` + TestClient + X-API-Key; seed the loop, tick once, assert a GREEN draft artifact appears and an AUTO_CAPPED verb queues an approval.

- [ ] **Step 1: failing test** (key behaviors)

```python
# tests/test_portfolio_cockpit_api.py
import os
from fastapi import FastAPI
from fastapi.testclient import TestClient

HEAD = {"X-API-Key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("API_KEY", "k")
    from narai.api.routes.portfolio_cockpit_admin import router
    app = FastAPI(); app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_seed_then_overview(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.post("/api/narai/portfolio/biz/n8n/seed", headers=HEAD).json()["ok"] is True
    ov = c.get("/api/narai/portfolio/biz/n8n/overview", headers=HEAD).json()
    assert ov["business"] == "n8n"
    assert ov["steps"][0]["verb"] == "research_niche"
    assert c.get("/api/narai/portfolio/biz/n8n/overview").status_code == 401  # auth


def test_tick_drafts_then_artifact_listed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/narai/portfolio/biz/n8n/seed", headers=HEAD)
    r = c.post("/api/narai/portfolio/biz/n8n/tick", headers=HEAD).json()
    assert r["status"] == "executed"          # first GREEN step ran (drafted)
    arts = c.get("/api/narai/portfolio/biz/n8n/artifacts", headers=HEAD).json()["artifacts"]
    assert any(a["kind"] == "research" for a in arts)
```

- [ ] **Step 2: run → fail. Step 3: implement** (full router):

```python
# narai/api/routes/portfolio_cockpit_admin.py
"""Per-business Build Cockpit API. Drives one business's supervisor loop through
the Plan-1 engine via the decoupled adapter registry. GREEN verbs draft artifacts;
auto_capped verbs queue for approval (ctx_for returns falsy preconditions)."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException

from core.portfolio import adapters, loops, registry, rollup, seed, state, paths

router = APIRouter(prefix="/api/narai/portfolio/biz", tags=["portfolio-cockpit"])


def verify_admin_api_key(x_api_key: str = Header(None)) -> bool:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API not configured (API_KEY env missing)")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True


def _require(slug: str):
    b = registry.get_business(slug)
    if b is None:
        raise HTTPException(404, f"unknown business {slug!r}")
    return b


@router.get("/{slug}/overview")
def overview(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    b = _require(slug)
    st = state.load_state(slug)
    steps = loops.load_loop(slug)
    nxt = loops.select_next_step(steps, st)
    done, pend = set(st["completed_verbs"]), set(st["pending_verbs"])
    out = []
    for s in steps:
        if s.verb in done:
            sstate = "completed"
        elif s.verb in pend:
            sstate = "pending"
        elif nxt is not None and s.verb == nxt.verb:
            sstate = "next"
        else:
            sstate = "todo"
        out.append({"verb": s.verb, "class": s.action_class.value, "state": sstate})
    return {"business": slug, "name": b.name, "phase": st.get("phase", "planning"),
            "steps": out, "completed": len(done), "pending": len(pend)}


@router.get("/{slug}/artifacts")
def artifacts(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    root = paths.business_dir(slug) / "artifacts"
    items = []
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                items.append({"kind": p.parent.name, "name": p.name, "path": str(p)})
    return {"artifacts": items}


@router.get("/{slug}/audit")
def audit(slug: str, limit: int = 50, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    rows = [r for r in rollup.recent_audit(limit=500) if r.get("business") == slug]
    return {"audit": rows[:limit]}


@router.post("/{slug}/tick")
def tick(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    result = loops.tick(slug, adapters.adapter_for, adapters.ctx_for)
    if result is None:
        return {"status": "idle", "detail": "no step ready"}
    return {"status": result.status, "verb": getattr(result, "detail", ""), "detail": result.detail}


@router.post("/{slug}/seed")
def seed_loop(slug: str, _=Depends(verify_admin_api_key)) -> dict:
    _require(slug)
    if slug != "n8n":
        raise HTTPException(400, "only the n8n pilot loop is seedable in Plan 3")
    seed.seed_n8n_loop()
    return {"ok": True}
```

- [ ] **Step 4: run → pass. Step 5: commit**

```bash
git add narai/api/routes/portfolio_cockpit_admin.py tests/test_portfolio_cockpit_api.py
git commit -m "feat(wmos): per-business Build Cockpit router (tick/overview/artifacts/audit/seed)"
```

---

### Task 5: mount cockpit router + `/admin/portfolio/{slug}` serve route

**Files:**
- Modify: `core/api.py` (independent top-level mount + serve route, located by content anchors)
- Create: `frontend/admin/portfolio_cockpit.html` (placeholder; Task 6 fills it)
- Test: `tests/test_portfolio_cockpit_mount.py`

**Interfaces:** Produces `GET /admin/portfolio/{slug}` (serves cockpit HTML, injects `%%API_KEY%%`) and the mounted `/api/narai/portfolio/biz/*` endpoints on the real app. The serve route must be registered so it does NOT shadow `GET /admin/portfolio` (the HQ, exact match) — FastAPI matches the exact path first, so `/admin/portfolio/{slug}` is safe alongside `/admin/portfolio`.

- [ ] **Step 1: failing test**

```python
# tests/test_portfolio_cockpit_mount.py
def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path)); monkeypatch.setenv("API_KEY", "k")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_cockpit_html_served(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/admin/portfolio/n8n").status_code == 200


def test_hq_still_served(monkeypatch, tmp_path):  # the {slug} route didn't shadow HQ
    c = _client(monkeypatch, tmp_path)
    assert c.get("/admin/portfolio").status_code == 200


def test_cockpit_api_mounted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/narai/portfolio/biz/n8n/seed", headers={"X-API-Key": "k"})
    r = c.get("/api/narai/portfolio/biz/n8n/overview", headers={"X-API-Key": "k"})
    assert r.status_code == 200
```

- [ ] **Step 2: run → fail (404s). Step 3a: mount block** — find the `portfolio_admin router skipped` anchor in `core/api.py` (the independent HQ mount from Plan 2) and insert AFTER its except line:

```python

# Portfolio Build Cockpit API — per-business operator surface
try:
    from narai.api.routes.portfolio_cockpit_admin import router as _portfolio_cockpit_rt
    app.include_router(_portfolio_cockpit_rt)                    # /api/narai/portfolio/biz/*
except Exception as _pc_exc:
    logging.getLogger("api").warning(f"portfolio_cockpit router skipped: {_pc_exc}")
```

- [ ] **Step 3b: serve route** — find `serve_portfolio_admin` in `core/api.py` and insert AFTER its function body:

```python
@app.get("/admin/portfolio/{slug}", response_class=HTMLResponse)
async def serve_portfolio_cockpit(slug: str):
    """Per-business Build Cockpit. API at /api/narai/portfolio/biz/{slug}/*."""
    path = ROOT / "frontend" / "admin" / "portfolio_cockpit.html"
    if not path.exists():
        return HTMLResponse("<h1>portfolio_cockpit.html not found</h1>", status_code=404)
    html = path.read_text(encoding="utf-8")
    if _API_KEY:
        sanitized = "".join(c for c in _API_KEY if 32 <= ord(c) <= 126).strip()
        html = html.replace("'%%API_KEY%%'", f"'{sanitized}'")
    return HTMLResponse(html, headers={"Cache-Control": "no-store, no-cache"})
```

- [ ] **Step 3c: placeholder** `frontend/admin/portfolio_cockpit.html`:

```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Build Cockpit · W-MOS</title></head>
<body><h1>W-MOS Build Cockpit</h1><script>const K='%%API_KEY%%';</script></body></html>
```

- [ ] **Step 4: run → pass. Step 5: commit**

```bash
git add core/api.py frontend/admin/portfolio_cockpit.html tests/test_portfolio_cockpit_mount.py
git commit -m "feat(wmos): mount Build Cockpit router + per-slug serve route"
```

---

### Task 6: Build Cockpit dashboard HTML

**Files:**
- Modify: `frontend/admin/portfolio_cockpit.html` (full dashboard)
- Test: `tests/test_portfolio_cockpit_html.py`

**Interfaces:** single-file vanilla-JS cockpit; reads `slug` from `location.pathname` (`/admin/portfolio/<slug>`); tabs Overview / Build / Artifacts / Audit; calls `/api/narai/portfolio/biz/{slug}/*`; a "Seed loop" button (n8n) and a "Run next step" button that POSTs `/tick` and re-renders.

- [ ] **Step 1: failing test**

```python
# tests/test_portfolio_cockpit_html.py
from pathlib import Path
def test_cockpit_html_structure():
    t = Path("frontend/admin/portfolio_cockpit.html").read_text(encoding="utf-8")
    assert "'%%API_KEY%%'" in t
    assert "/api/narai/portfolio/biz/" in t
    for m in ['data-tab="overview"', 'data-tab="build"', 'data-tab="artifacts"', 'data-tab="audit"']:
        assert m in t
    assert "X-API-Key" in t
    assert "location.pathname" in t   # derives slug from URL
```

- [ ] **Step 2: run → fail. Step 3: write the full cockpit HTML** mirroring `portfolio.html`'s structure (same `:root` CSS, `api()` wrapper with `'%%API_KEY%%'` + `X-API-Key` + `esc()` that escapes `& < > ' "`), deriving `const SLUG = location.pathname.split('/').filter(Boolean).pop();` and `const API = '/api/narai/portfolio/biz/'+SLUG;`. Tabs: **Overview** (phase + step list with state badges), **Build** ("Seed loop" + "Run next step" buttons calling `/seed` and `/tick`, showing the last tick result), **Artifacts** (table from `/artifacts`), **Audit** (table from `/audit`). Reuse the exact `key()`, `api()`, `esc()`, `err()`, and tab-switch code from `frontend/admin/portfolio.html` (copy them verbatim — they're the established, reviewed pattern), changing only the `API` base and the loaders. Every dynamic field passes through `esc()`.

(The implementer copies `portfolio.html`'s `<style>` + `key()/api()/esc()/err()` block verbatim, then writes the four loaders + the Build-tab buttons. ~250 lines.)

- [ ] **Step 4: run → pass. Step 5: full suite + commit**

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_*.py -q
git add frontend/admin/portfolio_cockpit.html tests/test_portfolio_cockpit_html.py
git commit -m "feat(wmos): Build Cockpit dashboard UI (overview/build/artifacts/audit)"
```

---

## Self-Review

**1. Spec coverage (spec §3.1 cockpit, §4 loop, §6 cockpit tabs, §7 n8n pilot):** cockpit surface §3.1 → Tasks 4/5/6; loop schema §4 → Task 3 seed; cockpit tabs §6 → Task 6; n8n verbs §7 → Task 2 adapters + Task 3 loop. ✅ Real external actions stay gated (auto_capped → queue) per §2 envelope.

**2. Placeholder scan:** Task 5 placeholder HTML is intentional + replaced in Task 6. No TBD/TODO in shipped code. The infra adapter is a documented stub (greenfield deploy), not a placeholder. ✅

**3. Type consistency:** every adapter implements `run(action)->dict`; `adapter_for`/`ctx_for` (Task 3) match `loops.tick`'s params (Plan 1); the cockpit router (Task 4) calls them and `seed.seed_n8n_loop` (Task 3); router paths match the UI calls (Task 6) and mount (Task 5). ✅

## Out of Scope (Plan 4)

- Real precondition facts in `ctx_for` (warmup/approval/cost-ceiling) so auto_capped verbs can actually auto-fire; arming the scheduler; wiring `cold_outreach.send_sequences` live behind the gate; real infra/deploy; the `approvals.jsonl` write-race fix; the envelope fail-closed + budget-breach tests; reconciling HQ Overview columns with spec §5. The other 9 businesses' loops/cockpits.
