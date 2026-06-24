# W-MOS Precondition Evaluation Framework Implementation Plan (Plan 5 — safe parts only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the cockpit's `ctx_for` REAL precondition facts (computed from approvals history, budget, a daily-send counter, and per-business flags) so the envelope's auto-fire-within-caps logic is genuinely evaluated — while staying fail-safe (unknown → False), inert (adapters unchanged), and dormant (scheduler untouched).

**Architecture:** A new `core/portfolio/preconditions.py` computes each named precondition from the best real source, defaulting any it can't compute to `False`. Because `loops.tick`'s `ctx_for(step)` is business-blind, the **cockpit** binds the business via `preconditions.make_ctx_for(slug)`; the dormant orchestrator sweep keeps the global `adapters.ctx_for` (`{}`). Small state helpers (`set_flag`/`get_flag`, `record_send`/`send_count`) back the flag- and cap-based preconditions. No adapter, no `dispatch`, no orchestrator dormancy, and no real external action is touched.

**Tech Stack:** Python 3 stdlib, FastAPI, pytest. Reuses Plan-1 `state`/`budget`/`loops`, Plan-3 `adapters`/`seed`.

## Global Constraints

- **Repo / branch:** `wheellsverse-bots` @ `_apexdeploy`, on top of Plan 4 (HEAD `2db7a99`). Paths relative to repo root.
- **File header:** new modules start with `from __future__ import annotations`.
- **Fail-safe:** any precondition `preconditions.py` cannot positively compute resolves to `False` (queues, never auto-fires). Unknown precondition names → `False`.
- **Still inert + dormant:** do NOT modify any adapter, `actions.dispatch`, the orchestrator's dormancy/kill gates, or set `WMOS_ORCHESTRATOR_ENABLED`. Auto-fire here only ever reaches the inert `OutreachSendAdapter` (`would_send`) / `SiteAdapter` (draft) / `InfraAdapter` (stub) via the operator-triggered cockpit tick.
- **No engine signature change:** do NOT change `loops.tick` / `actions.dispatch`. The cockpit passes a business-bound `ctx_for` closure; `adapters.ctx_for` (global `{}`) is unchanged.
- **Clocks at the boundary:** `preconditions.evaluate(...)` takes optional `today`/`month` (default reads the real clock); tests pass fixed values.
- **truth_verification skill applies.** Run tests from repo root.
- **git hygiene:** stage ONLY each task's named files; never `git add -A`.

---

### Task 1: state flag + daily-send-count helpers

**Files:**
- Modify: `core/portfolio/state.py` (add 4 helpers)
- Test: `tests/test_portfolio_flags.py`

**Interfaces:**
- Produces: `set_flag(business, key, value) -> None`, `get_flag(business, key, default=False) -> bool`, `record_send(business, day, n=1) -> None`, `send_count(business, day) -> int`. Backed by `state.json` keys `"flags"` (dict) and `"sends"` (dict day→int); `load_state` already preserves unknown keys.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_flags.py
from core.portfolio import state


def test_flag_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert state.get_flag("n8n", "warmup_complete") is False        # default
    state.set_flag("n8n", "warmup_complete", True)
    assert state.get_flag("n8n", "warmup_complete") is True          # persisted (re-read)
    # flags don't disturb the rest of state
    assert state.load_state("n8n")["phase"] == "planning"


def test_send_counter(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert state.send_count("n8n", "2026-06-23") == 0               # default
    state.record_send("n8n", "2026-06-23", 3)
    state.record_send("n8n", "2026-06-23")                          # +1
    assert state.send_count("n8n", "2026-06-23") == 4
    assert state.send_count("n8n", "2026-06-24") == 0              # per-day
```

- [ ] **Step 2: Run → fail** (`AttributeError: ... has no attribute 'set_flag'`).

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_flags.py -v`

- [ ] **Step 3: Implement.** Add to `core/portfolio/state.py` (after `save_state`):

```python
def get_flag(business: str, key: str, default: bool = False) -> bool:
    return bool(load_state(business).get("flags", {}).get(key, default))


def set_flag(business: str, key: str, value: bool) -> None:
    s = load_state(business)
    s.setdefault("flags", {})[key] = bool(value)
    save_state(business, s)


def send_count(business: str, day: str) -> int:
    return int(load_state(business).get("sends", {}).get(day, 0))


def record_send(business: str, day: str, n: int = 1) -> None:
    s = load_state(business)
    sends = s.setdefault("sends", {})
    sends[day] = int(sends.get(day, 0)) + int(n)
    save_state(business, s)
```

- [ ] **Step 4: Run → pass. Step 5: Commit**

```bash
git add core/portfolio/state.py tests/test_portfolio_flags.py
git commit -m "feat(wmos): per-business flags + daily-send counter helpers"
```

---

### Task 2: `preconditions.py` — real precondition evaluation

**Files:**
- Create: `core/portfolio/preconditions.py`
- Test: `tests/test_portfolio_preconditions.py`

**Interfaces:**
- Consumes: `state.list_approvals`/`get_flag`/`send_count`, `budget.would_exceed`, `loops.LoopStep` (duck-typed: `.verb`, `.preconditions`).
- Produces:
  - `evaluate(business, step, *, today=None, month=None) -> dict[str, bool]` — one bool per name in `step.preconditions`.
  - `make_ctx_for(business) -> Callable[[step], dict]` — a business-bound `ctx_for(step)`.
  - `DAILY_CAP = 50`.
- Mapping: `campaign_approved_once` / `page_approved_once` / `first_of_kind_approved` → the step's verb was ever operator-approved (status in approved/executing/executed); `under_daily_cap` → `send_count(business, today) < DAILY_CAP`; `under_cost_ceiling` → `not budget.would_exceed(business, 0.0, month)`; `warmup_complete` / `teardown_handle` / `unpublish_handle` → `get_flag`; anything else → `False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_preconditions.py
from core.portfolio import preconditions, state, budget
from core.portfolio.actions import Action, ActionClass
from core.portfolio.loops import LoopStep


def _step(verb, preconds):
    return LoopStep(verb, "agent", ActionClass.AUTO_CAPPED, preconds)


def test_unknown_precondition_is_false(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    out = preconditions.evaluate("n8n", _step("v", ["totally_made_up"]), today="2026-06-23", month="2026-06")
    assert out == {"totally_made_up": False}


def test_approval_history_precondition(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    step = _step("run_outreach_campaign", ["campaign_approved_once"])
    assert preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")["campaign_approved_once"] is False
    aid = state.queue_approval(Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    state.resolve_approval(aid, "approved")
    assert preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")["campaign_approved_once"] is True


def test_daily_cap_and_flags_and_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    step = _step("run_outreach_campaign", ["under_daily_cap", "warmup_complete", "under_cost_ceiling"])
    out = preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")
    assert out["under_daily_cap"] is True        # 0 sends < cap
    assert out["warmup_complete"] is False        # flag unset
    assert out["under_cost_ceiling"] is True      # nothing spent
    state.set_flag("n8n", "warmup_complete", True)
    state.record_send("n8n", "2026-06-23", preconditions.DAILY_CAP)   # hit the cap
    budget.record_spend("n8n", 999.0, "x", "2026-06")                 # blow the ceiling
    out2 = preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")
    assert out2["under_daily_cap"] is False
    assert out2["warmup_complete"] is True
    assert out2["under_cost_ceiling"] is False


def test_make_ctx_for_binds_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    ctxf = preconditions.make_ctx_for("n8n")
    out = ctxf(_step("v", ["warmup_complete"]))
    assert out == {"warmup_complete": False}
```

- [ ] **Step 2: Run → fail. Step 3: Implement**

```python
# core/portfolio/preconditions.py
"""Real precondition evaluation for the W-MOS envelope's auto-fire-within-caps tier.

Computes each named precondition from a real source; ANYTHING it cannot positively
compute resolves to False (fail-safe → queues, never auto-fires). The cockpit binds
a business via make_ctx_for(slug); the dormant sweep keeps the {} default. No adapter,
dispatch, or scheduler is touched — auto-fire here still only reaches inert adapters.
"""
from __future__ import annotations

import time
from typing import Callable

from core.portfolio import budget, state

DAILY_CAP = 50
_APPROVED_STATES = {"approved", "executing", "executed"}
_APPROVAL_PRECONDS = {"campaign_approved_once", "page_approved_once", "first_of_kind_approved"}
_FLAG_PRECONDS = {"warmup_complete", "teardown_handle", "unpublish_handle"}


def _verb_ever_approved(business: str, verb: str) -> bool:
    return any(
        a.get("business") == business
        and a.get("verb") == verb
        and a.get("status") in _APPROVED_STATES
        for a in state.list_approvals()
    )


def _one(business: str, verb: str, name: str, today: str, month: str) -> bool:
    if name in _APPROVAL_PRECONDS:
        return _verb_ever_approved(business, verb)
    if name == "under_daily_cap":
        return state.send_count(business, today) < DAILY_CAP
    if name == "under_cost_ceiling":
        return not budget.would_exceed(business, 0.0, month)
    if name in _FLAG_PRECONDS:
        return state.get_flag(business, name, False)
    return False  # fail-safe: an unknown precondition never auto-passes


def evaluate(business: str, step, *, today: str | None = None, month: str | None = None) -> dict:
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    month = month or time.strftime("%Y-%m", time.gmtime())
    verb = getattr(step, "verb", "")
    return {name: _one(business, verb, name, today, month)
            for name in getattr(step, "preconditions", [])}


def make_ctx_for(business: str) -> Callable[[object], dict]:
    def ctx_for(step) -> dict:
        return evaluate(business, step)
    return ctx_for
```

- [ ] **Step 4: Run → pass. Step 5: Commit**

```bash
git add core/portfolio/preconditions.py tests/test_portfolio_preconditions.py
git commit -m "feat(wmos): real precondition evaluation (fail-safe, business-bound ctx_for)"
```

---

### Task 3: wire the cockpit tick to use real preconditions

**Files:**
- Modify: `narai/api/routes/portfolio_cockpit_admin.py` (tick uses `preconditions.make_ctx_for(slug)`)
- Test: `tests/test_portfolio_preconditions_tick.py`

**Interfaces:**
- Consumes: `preconditions.make_ctx_for`, `loops.tick`, `adapters.adapter_for`, `seed`.
- Produces: cockpit `POST /{slug}/tick` now evaluates real preconditions (auto_capped verbs auto-fire ONLY when all met; else queue).

- [ ] **Step 1: Write the failing test** (engine-level, deterministic — proves the bound ctx_for drives auto-fire vs queue)

```python
# tests/test_portfolio_preconditions_tick.py
from core.portfolio import adapters, preconditions, seed, state, loops
from core.portfolio.actions import Action, ActionClass


def _advance_to_outreach(slug="n8n"):
    seed.seed_n8n_loop()
    for v in ["research_niche", "build_workflow_pack", "generate_lead_list", "draft_outreach"]:
        state.mark_completed(slug, v)


def test_auto_fires_when_all_preconditions_met(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _advance_to_outreach()
    # satisfy run_outreach_campaign's [warmup_complete, campaign_approved_once, under_daily_cap]
    state.set_flag("n8n", "warmup_complete", True)
    aid = state.queue_approval(Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    state.resolve_approval(aid, "approved")               # campaign_approved_once -> True
    res = loops.tick("n8n", adapters.adapter_for, preconditions.make_ctx_for("n8n"))
    assert res.status == "executed"                       # auto-fired (inert would_send)
    assert res.output == {"status": "would_send",
                          "note": "gated send — wire cold_outreach.send_sequences(confirm=True, live=True) on approval",
                          "verb": "run_outreach_campaign"}


def test_queues_when_a_precondition_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _advance_to_outreach()
    # warmup flag NOT set -> still queues
    aid = state.queue_approval(Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    state.resolve_approval(aid, "approved")
    res = loops.tick("n8n", adapters.adapter_for, preconditions.make_ctx_for("n8n"))
    assert res.status == "queued"
```

- [ ] **Step 2: Run → these pass already at the engine level once Task 2 exists; confirm they pass, then make the COCKPIT use the bound ctx_for.**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_preconditions_tick.py -v`
Expected: PASS (the engine wiring is exercised directly). If they already pass, proceed to wire the cockpit (Step 3) so the HTTP surface uses the same path.

- [ ] **Step 3: Wire the cockpit.** In `narai/api/routes/portfolio_cockpit_admin.py`, add `preconditions` to the `from core.portfolio import ...` import line, and change the `tick` route's `loops.tick(...)` call from `adapters.ctx_for` to the bound closure:

```python
    result = loops.tick(slug, adapters.adapter_for, preconditions.make_ctx_for(slug))
```

- [ ] **Step 4: Run the cockpit + full suite to verify no regression**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_cockpit_api.py tests/test_portfolio_preconditions_tick.py -v && python -m pytest tests/test_portfolio_*.py -q`
Expected: cockpit tests still green (GREEN verbs ignore ctx; the existing tick test runs `research_niche` which is GREEN), the two new tick tests green, full suite green.

- [ ] **Step 5: Commit**

```bash
git add narai/api/routes/portfolio_cockpit_admin.py tests/test_portfolio_preconditions_tick.py
git commit -m "feat(wmos): cockpit tick evaluates real preconditions (auto-fire within caps, inert)"
```

---

## Self-Review

**1. Spec coverage:** real `ctx_for` precondition facts (Plan-3/4 carry-forward; spec §2 auto-fire-within-caps) → Tasks 2/3. Fail-safe defaults + inert + dormant → Global Constraints (no adapter/dispatch/orchestrator change). ✅
**2. Placeholder scan:** No TBD/TODO. The flag-based preconditions (warmup/teardown/unpublish) default False until an operator sets them — that's the intended fail-safe, not a placeholder. ✅
**3. Type consistency:** `evaluate(business, step, *, today, month)` + `make_ctx_for(business)` (Task 2) used unchanged in Task 3 and tests; `state.set_flag/get_flag/send_count/record_send` (Task 1) consumed by Task 2; `budget.would_exceed(slug, amount, month)` and `state.list_approvals` are existing signatures. ✅

## Out of Scope (operator-gated arming — NOT in this plan)
Incrementing the real send counter on actual sends; wiring `cold_outreach.send_sequences(live=True)` so `OutreachSendAdapter` truly sends; real `warmup`/`teardown`/`unpublish` data sources + a real deploy provider; budget enforcement inside the dormant sweep; flipping `WMOS_ORCHESTRATOR_ENABLED`. Each is irreversible/outward-facing and requires explicit operator authorization.
