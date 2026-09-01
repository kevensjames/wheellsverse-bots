# KAI Owner Daily Brief + Owner Queue (§1-8, §24-34)

How KAI decides what — if anything — reaches you, and how "Today" is assembled. Dormant on
`feat/kai-exec-appb-integration`. Reuses the existing `proposals_store` (the owner queue) and extends
`briefing.py`; there is **no second queue**.

## Modules
| File | Role |
|---|---|
| `holding/owner_queue.py` | reconciled OWNER work → prepared `OwnerAction` → existing `proposals_store` |
| `holding/proposals_store.py` | `resolve_absent()` auto-resolves owner items whose blocker vanished (§3) |
| `holding/briefing.py` | `today_for_you()` (7 sections) + `what_do_you_need_from_me()` + `what_should_i_do_today()` |
| tests | `test_owner_queue.py` (7/7), `test_today_brief.py` (8/8) |

## The owner boundary
- **KAI-doable work never reaches you (§24).** Only A3+/OWNER-assigned tasks (and work the engine
  marked `OWNER_QUEUED`) become owner items. A0/A1 work KAI does itself.
- **Prepared, not raw (§2).** Each `OwnerAction` carries: company, source_key, priority, title, reason,
  `kai_completed` (what KAI already did), `exact_owner_action` (the irreducible human step),
  surface, estimated_time, deadline, risk_if_delayed, next_after_owner, evidence. Generic titles
  ("review startup", "work on marketing", "fix deployment") are rejected — never queued.
- **One item per requirement (§1).** Deduped by a stable `source_key` via the existing
  `sync_open` dedup; an existing unresolved requirement is UPDATEd, never duplicated each cycle.
- **Auto-resolve (§3).** When a blocker disappears (its source_key is no longer active), the open
  proposal is marked `superseded` by `resolve_absent()` — stale owner work never lingers in Today.

## Today For You (§4-5)
`today_for_you()` returns 7 sections: **TODAY FOR YOU** · KAI COMPLETED SINCE LAST VISIT · KAI WORKING
NOW · MATERIAL CHANGES · RISKS · DECISIONS NEEDED · WATCHING. Owner actions ranked by
CRITICAL→HIGH→MEDIUM→INFO then explicit priority, **capped at 3–7** with the remainder grouped (never
silently dropped). Every Today item links back to its company + source_key + evidence (§34 — no orphan
advice). An empty queue yields the exact line **"No action required right now."** (§6) — KAI invents
nothing.

## The three owner questions
- **"What do you need from me?" (§7)** → only current unresolved owner-gated actions; when none:
  *"Nothing currently requires your action."*
- **"What should I do today?" (§8)** → from the real reconciled queue, never advice generated at query
  time.
- (**"What are you / are you conscious?"** answered by `OperationalSelfModel` — operational only,
  never a consciousness claim.)
