# KAI Omnipresence — §44 Compartmentalization (Qubes/Genode principles, as actually applied)

Phase 9 governance doc. **Read-only mapping — adds no module, enables nothing.** Every row names the file
and symbol that enforces the principle today; §"Gaps" says what is NOT compartmentalized. Paths are
relative to the repo root; line numbers are as of branch `feat/kai-cyber-operations`.

## 1. Principle → real enforcement point

| Qubes/Genode principle | Where it is applied | What it enforces |
|---|---|---|
| **Least authority** (a principal holds only the scopes its role needs) | `core/operator_session.py:65` `ROLE_SCOPES` — owner=ALL, operator={read, write, kai.chat}, viewer={read}; `Principal` is a frozen dataclass (`:72`) so a resolved identity cannot be mutated mid-request; `mint_session` refuses unknown roles (`:135`) | operator is deliberately NOT financial/destructive/ultra; those are owner-key only |
| | `backend/app/routers/admin_chat.py:164` `require_kai_ultra` — applied at 38 App B entry points | scope is enforced at EVERY reachable entry, not only at the bridge (the 2026-08-22 RBAC lesson) |
| | `backend/app/services/holding/worker_health.py` `execution_authority` | liveness ≠ authority: an ONLINE/IDLE/BUSY worker reports `NONE` unless brakes #1+#2 (+#3) are on |
| **Capability tokens** (authority is an explicit, unforgeable grant, never inferred) | `backend/app/services/holding/a2_framework.py:124` `A2GrantRegistry` — per-(action_type, capability, company, environment) grants; default EMPTY → `NEEDS_CERTIFICATION`; non-production only. The single grant: `a2_wiring.py:22` `SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1` | A2 prepare-only work runs only under a named grant tuple |
| | `core/operator_session.py:80` `Principal.has(scope)` over a `frozenset` of scopes | the token carries its authority; nothing is looked up ambiently at use time |
| | `backend/app/services/capability/manifest.py` `security_tier` / `automatic_activation_allowed` / `risk_class=RESTRICTED` (read by `capabilities_answer.status_of`) | RESTRICTED / tier≥3 capabilities are never auto-selected; they need an authorized mission + operator approval |
| **Protection domains** (writers cannot touch each other's state) | `backend/app/services/capability/coding.py:200` `assign_worktrees` — one branch + worktree per WRITABLE worker; the primary certified checkout is never handed out; duplicate ids refused | no two workers share files (§12/§13) |
| | `backend/app/services/holding/a2_wiring.py:32` `make_git_worktree_fn` — a REAL `git worktree add -b`, disposable, idempotent on retry; `remove_worktree` (`:56`) | A2 edits happen in a throwaway tree; the primary checkout is never written |
| | Two deployments (App A `core/api.py`, App B `backend/app/main.py`) linked ONLY by `core/kai_bridge.py` | the brain and the admin shell are separate processes/hosts with one narrow seam |
| **Trust separation** (external output is DATA until governance says otherwise) | `backend/app/services/capability/results.py:132` `NormalizedResult.trust = "UNTRUSTED"` always; `:89` `scan_for_injection` surfaces markers (a signal — never an approval) | a hostile README/PR/log cannot become an instruction |
| | `results.py:183` `sanitize_external_result` — re-owns `trust`/`authorized`/`injection_flags` on EVERY adapter result; called from `capability/invocation.py:218` (`governed_invoke`) | an adapter cannot self-authorize or suppress the injection signal |
| | `results.py:198` `neutralize_untrusted_context` — fences holding context composed into the LLM prompt with a per-call nonce; called from `backend/app/services/nai_brain/brain.py:77` | injected "enable A2 / approve / run shell" text reaches the model as fenced data |
| | `backend/app/services/holding/os_lab/runtimes.py:328` `OsLabAuthorityGuard` — an `os_lab:*` source may only yield EVIDENCE; authority actions → `REJECTED`; unknown → `REJECTED_UNKNOWN_ACTION` (fail closed) | no OS/runtime is ever an authority plane (§165) |
| **No ambient authority / default-deny** | `backend/app/services/capability/execution.py:57` `_ip_forbidden` + `:62` `validate_public_url` — http(s) only; literal AND resolved private/loopback/link-local/multicast/metadata addresses rejected; applied at `:129` | default-deny egress for the fabric's URL-taking operations (SSRF closed) |
| | `core/kai_bridge.py:172-191` — fails closed (404) when `KAI_BRIDGE_ENABLED` is off; method allowlist; read-only prefixes GET-only; path-prefix allowlist + `..` rejection; authN; scope authZ (ultra = owner-only); fixed upstream from config, never from the request; raw `X-API-Key` never forwarded | the only cross-app link is an allowlist, not a proxy |
| | `backend/app/services/holding/brakes.py:112` `stop_engaged` — an UNREADABLE STOP record is treated as ENGAGED; honored by `holding_cycle.py:46` (`build_live_engine` forces the config-read brakes OFF) and `a2_dispatch.py:46` (`enqueue_a2_coding_job` → `STOP_ENGAGED`) | §97 STOP fails closed; owner-only mutation via the same `ROLE_OWNER`+`kai.ultra` identity model |
| | `worker_health.credential_present` — env-key PRESENCE only, never a value (§120); `backend/app/services/governance/audit_log.py:95` `_redact` | secrets never enter a report or an audit row |

## 2. Gaps — what is NOT compartmentalized yet (honest)

1. **No OS-level protection domain.** App A and App B are each ONE Python process. Capability adapters, holding
   modules and the A2 subprocesses (`git`, the certified suite) run in-process / as children with KAI's own POSIX
   privileges. There is no seccomp, namespace, container or VM per capability (grep: none). Qubes' "one VM per
   domain" has no analogue; a worktree is a *git* boundary, not a filesystem/namespace boundary — a worker in its
   worktree can still read the primary checkout and the process environment.
2. **Ambient credentials.** Provider keys live in the process env. `worker_health` reads presence only, but every
   in-process adapter and child process inherits the whole env. No per-capability credential scoping, vault, or
   short-lived tokens.
3. **Egress is guarded per operation, not per process.** `_ip_forbidden` covers only the URL-taking fabric
   operations (`execution.py:129`). Subprocess workers and MCP/CLI adapters have unrestricted network access from
   this app; there is no process-level network policy.
4. **Coarse human roles.** `ROLE_SCOPES` has three roles with app-wide scopes — no per-company or per-capability
   scopes for people. A2 grants are fine-grained but cover only the A2 prepare path in non-production.
5. **The injection boundary is a marker scan, not a sandbox.** `scan_for_injection` is regex-based (signal +
   quarantine, not containment). `neutralize_untrusted_context` has exactly ONE call site
   (`nai_brain/brain.py:77`); any new prompt-composition path must route through it explicitly or it is unfenced.
6. **`OsLabAuthorityGuard` guards nothing live yet.** `GUARD` (`runtimes.py:352`) has no production caller because
   Phase 10 is catalog-only — nothing is installed or booted. It is exercised by tests only.
7. **STOP does not preempt.** It refuses NEW consequential work (next engine build / A2 enqueue); claimed/running
   jobs run to completion or lease expiry (documented in `brakes.py`). No kill of in-flight work.
8. **The bridge allowlist is certified locally only.** `KAI_BRIDGE_ENABLED` defaults OFF; there is no hosted-edge
   certification (see `docs/KAI_ADMIN_MERGE_HOSTED_EDGE_AND_PROD_RUNBOOK.md`).

## 3. Verify (read-only, no DB, from `backend/`)

```
PYTHONPATH=..:. DATABASE_URL=postgresql://u:p@localhost:5432/x python3 -m app.services.holding.test_brakes
PYTHONPATH=..:. DATABASE_URL=postgresql://u:p@localhost:5432/x python3 -m app.services.holding.test_worker_health
PYTHONPATH=..:. DATABASE_URL=postgresql://u:p@localhost:5432/x python3 -m app.services.holding.test_a2_framework
```

Closing a gap above means a new enforcement point with a named file + a check, then a new row in §1 — never a
prose promise. Rows are removed only when the code is.
