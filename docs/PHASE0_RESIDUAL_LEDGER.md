# CEO truth gate — Phase 0 residual ledger

Reconciles the count. An earlier report said **"Seven Phase 0 items still open"** and then listed
**six**. The list was wrong, not the number — but the number was right by accident, and the missing
item is a real one I had assumed complete.

**Phase 0 defines twelve items.** Five are complete. Seven are not. Each row below is decided by
reading the code on this branch, not by recollection.

The **browser authentication regression is not a Phase 0 item.** It was a PR #70 blocker, it is
complete (7 pages × 6 session states, 0 violations), and it is not counted here in either column.

---

## The twelve

| # | Phase 0 requirement | State | Evidence |
|---|---|---|---|
| 1 | Worker may be `IDLE` while executive state is `ATTENTION_REQUIRED` | **COMPLETE** | `attention_projection.py` (new, 201 lines); wired at `admin_holding.py:896-919`; 18/18 checks |
| 2 | All arrival briefs and summaries use the **same** attention projection | **OPEN** | See below |
| 3 | Health denominator comes from the displayed dimension registry | **COMPLETE** | `health_score.py` — `registered_dimensions`, `"{measured} of {registered} measured"`; production's "2 of 3" for seven displayed dimensions is now "2 of 7" |
| 4 | Separate service health from portfolio health | **OPEN** | Only `cross_company.py:301` carries a `portfolio_health` key; no split on the served health surface |
| 5 | Global `UNAVAILABLE` money authority vs product-specific `MOCK` | **COMPLETE** | `money_state.py` (new, 205 lines) — environment / authority / providers resolved separately, absent = `UNAVAILABLE`; 15/15 |
| 6 | A capability cannot be `AVAILABLE` without installed + certified + credentialed + policy-allowed + recently probed runtime | **OPEN** | No lifecycle gate implemented on this branch |
| 7 | Stale company facts show their date and become `STALE` / `UNVERIFIED` | **OPEN** | Not implemented |
| 8 | Group repeated entity-verification problems into one program with child entities | **OPEN** | Not implemented |
| 9 | Do not rank the Stripe consolidation idea as evidenced opportunity until sized | **COMPLETE** | `opportunity_engine.py` — `OPPORTUNITY_TO_SIZE` / `SIZED`, `REQUIRED_SIZING_FIELDS`, `sizing_status()` |
| 10 | Hide inactive voice controls; rename the palette as navigation while command execution is dark | **COMPLETE** | `kai-presence.js` — stop-listen button ships `hidden`, revealed only while listening; `holding.html` — "Command ⌘K" → "Navigate ⌘K", dialog relabelled "Navigation palette — jump to a panel" |
| 11 | Ingest hosted-verification evidence only for routes and behaviours actually tested | **OPEN** | Not implemented |
| 12 | Keep technical registry/timeline/evidence detail available without dominating the CEO summary | **OPEN** | Not implemented |

**Complete: 5 (items 1, 3, 5, 9, 10). Open: 7 (items 2, 4, 6, 7, 8, 11, 12).**

## Item 2 — the one the earlier list missed

I had counted this as complete because the projection is wired in and the arrival brief uses it. Both
halves of that are true, and the conclusion was still wrong.

- The **arrival brief** fetches `/admin/kai/holding/view` (`kai-presence.js:1291`), which carries
  `attention_state` — projection applied. ✅
- The **CEO summary panel** reads the same `/view` payload (`holding.html:578`, `:608-609`). ✅
- The **morning-briefing panel** does not. `holding.html:1260` calls
  `/admin/kai/holding/briefing`, which returns `run_morning_briefing(fetch_health=True)`
  (`admin_holding.py:84-87`) — untouched by the projection.

So the dashboard renders two summary surfaces whose priority ordering is produced by two different
code paths. `renderBrief` prints source-cited KPIs and a ranked priority list; it does **not** print a
contradictory attention *state*, which is why this is narrower than the item-1 defect. But "all
summaries use the same projection" is not yet true, and two ranked lists derived independently can
disagree about what matters most on the same screen.

Scoped deliberately out of this hotfix: routing the briefing through the projection changes what the
owner's morning report says, which is a CEO-surface behaviour change and not a truth-and-control fix.
It belongs in the Phase 0 continuation with the other six.

## Why the miscount happened

The residual list was assembled from memory of what had been built rather than by re-reading the
twelve requirements against the code. Item 2 had a module, a wiring point and a passing test suite,
and every one of those was real — none of them established that *every* displayed summary consumed
it. This ledger is written the other way round: requirement first, then the code that satisfies it,
or `OPEN`.
