# KAI Runtime Certification Wave (Parts A–C, §1-37)

Turning declared resolver mappings into genuinely-executable read/diagnose/verify capabilities for the
Holding Autonomous Work Engine. Dormant on `feat/kai-exec-appb-integration`; production untouched.

## Certification status (honest — §37, no overstating)
| Task type | Capability | Runtime | State |
|---|---|---|---|
| HEALTH_PROBE | `holding.health` | internal read over `signals.py` | ✅ CERTIFIED |
| CAPABILITY_HEALTH | `holding.capability_health` | CapabilityRegistry | ✅ CERTIFIED |
| **REPO_INSPECT** | `holding.repo` | in-process read-only `LocalGitProvider` (live git E2E) | ✅ **CERTIFIED_READ_ONLY** |
| **LOG_INSPECT** | `holding.logs` | two-stage-redacted `LocalLogFileProvider` | ✅ **CERTIFIED_REDACTED_READ_ONLY** ¹ |
| **RUN_INTERNAL_TEST** | `holding.internal_test` | allowlisted bounded-subprocess suite runner (real suite E2E) | ✅ **CERTIFIED_A1** |
| DEPLOYMENT_STATUS | `holding.deployment` | Railway read connector | `RUNTIME_PENDING` |
| BROWSER_VALIDATE | `playwright` | — | `RUNTIME_PENDING` (after internal-test cert) |
| TECH_DOC_LOOKUP | `context7` | — | `RUNTIME_PENDING` |

¹ The provider is certified; **no production log source is wired** — `register_log_source()` is empty by
default, so real services `BLOCK` until an ops-owned service→source map is configured.

Each certification is finalized only after its focused adversarial recheck (§42) passes.

## Part A — REPO_INSPECT (`repo_inspect.py`)
- Logical repo task, **not** `github.read` (§1): company → typed `RepositoryIdentity` → provider. An
  **explicit company allowlist** (`_LOCAL_MONOREPO_COMPANIES`) routes to the certified local provider;
  every other company → external provider with no certified backend → `BLOCKED_CAPABILITY`. No substring
  matching (a repo merely *named* `…wheellsverse-bots-fork` cannot reach the local provider).
- Read-only only (§4): no write git command exists. Sensitive-file **content denied upstream** (§5) on
  both the raw and the *resolved* path; **symlinks rejected** (`realpath != lexical`); traversal rejected;
  reads size-bounded + truncated (§7); content + evidence redacted (§6); FS root never leaked.

## Part B — LOG_INSPECT (`log_inspect.py`)
- Typed contract (§16): only `service/company/time_window/severity/bounded_limit/correlation_id`; any
  `command/shell/grep/path` field → denied. Source resolved from a **server-owned** service→source map
  (§17), never task input.
- **Two-stage redaction (§19):** the whole raw source is redacted at read (multiline-aware, so PEM
  blocks split across lines are caught) *before* assembly/persist, then the finished evidence is redacted
  again. Server-enforced bounds (§18). Evidence = matched/redaction counts + bounded excerpts (§22);
  never raw secret-bearing logs. Legitimate SHAs/UUIDs stay visible.

## Part C — RUN_INTERNAL_TEST (`internal_test.py`) — first A1
- Server-owned `TestSuiteRegistry`; the client submits a **suite_id only** (§27-28). Any
  `command/cwd/env/shell/args` in the payload is a hard denial; suite_id is regex-validated (no
  traversal/metacharacters §36); unknown/disabled/cross-company suites fail closed.
- Runner executes a **fixed arg list** in a bounded subprocess (`shell=False`, timeout), parses real
  passed/failed/skipped + exit status. **Test failure is a COMPLETED execution with `test_result=FAILED`**
  (§32), never an infra error. Evidence (§30) is real output, redacted; no agent summary substitutes.
  Isolated worker-plane dispatch for heavier/mutating suites is a declared follow-on (§35).

## Redactor hardening (from the adversarial reviews)
`redact()` now covers OpenAI (incl. `sk-proj-`/`sk-svcacct-`), GitHub (`ghp_`/`github_pat_`/`gh[opsur]_`),
Slack (`xox…`), Stripe (`sk_live_`), connection-string credentials (`scheme://user:pass@`), private
keys (incl. OPENSSH), JWTs, compound key=value names in flat strings (`aws_secret_access_key=…`), and
dict values under secret-named keys — while **not** redacting legitimate git SHAs.

## Production
UNCHANGED. Nothing here deploys on local test pass; all mappings run only behind the existing flags,
and only the operator runs `railway up` / `git push production`.
