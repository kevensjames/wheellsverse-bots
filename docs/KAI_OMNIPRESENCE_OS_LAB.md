# KAI Systems/OS Lab — Phase 10 (§39–44 / §113–117 / §165) — GOVERNED FRAMEWORK ONLY

Branch `feat/kai-cyber-operations` · worktree `/Users/jhonwheeler/wheellsverse-cyberops` · **isolated: no deploy, no merge, no MONEY_MODE change** · everything DARK.

**Status: CATALOG_ONLY.** This phase built metadata, typed policies, a state machine, and honest UNVERIFIED states. It did **not** clone, download, install, build, or QEMU-boot any external OS/repository, and added **no dependency and no config flag**. Pipeline *execution* is a later, separately gated step (isolated infra + supply-chain certification + explicit operator sign-off — §113/§117/§160).

Package: `backend/app/services/holding/os_lab/` (new files only; `frontend/admin/*`, `core/api.py`, and every Phase-9 module untouched).

| File | Owns |
|---|---|
| `catalog.py` | §115 governed OS catalog (11 entries) · §116 starting dispositions · §113 quarantine lifecycle (explicit chain, audited, fail-closed REJECTED from every non-terminal state; `BUILD_REVIEW`/`ISOLATED_EXECUTION` additionally gated on the `runtimes.EXECUTED` ledger) · §114 bounded verdict vocabulary + `record_verdict` fail-closed direction (kai may record only SUSPICIOUS/REJECTED/UNVERIFIED; the clean-scope verdict is operator-only, must match the attached report, and needs a FULL, fully-decided report) · §117 `GapJustification` adoption gate (`justify_adoption` operator-only) · `record_repo_instruction` (README = DATA, never policy). |
| `runtimes.py` | §40 Ultron `UltronSandboxRecord` (source read from the catalog — one spine; forbidden claims refused in any spelling) · §42 virtme-ng `RestrictedRuntime` + typed `KernelTestPolicy` with the hoisted `KERNEL_DENY` invariant · §43 syzkaller `SecurityLabRuntime` + `SecurityLabPolicy.admit()` · §165 `OsLabAuthorityGuard` (normalized source matching) · fail-closed `_is_production` · §102/§150 feature-registry rows · `install_gate`/`catalog_binding` (install truth + `source_consistent` derived from the catalog) · `os_lab_view` · `EXECUTED` ledger (all False). |
| `certification.py` | §41/§114 supply-chain certification pipeline as typed, ordered steps + a FROZEN report shape, and the §143 safe-fixture static scanner (sibling cluster). `core.security_scanner._COMPILED_PATTERNS` is the single base of the generic sweep; only OS-lab-specific categories are local. Only pure static checks over a supplied local inventory can run; every executable step is SKIPPED with reason `EXECUTION_GATED`, so a static-only report can never emit the clean-scope verdict — best is `UNVERIFIED`. `inventory_from_dir` follows no symlink and never opens a §30 forbidden target or an oversize file. |
| `fixtures/mimic_repo/` | §143 safe fixtures: benign mimics (a `curl … \| bash` string, an `~/.ssh/id_rsa` path string, a crontab line, a base64-like blob, an `.invalid`-TLD hostname, a `postinstall` hook) that must each FAIL their named static step. Nothing in it functions; shell fixtures exit before the mimic line; hostnames use the RFC 2606 reserved `.invalid` TLD. |
| `test_os_lab_runtimes.py` | 85 zero-framework checks (plain `python3`, pytest-discoverable). Includes a static scan asserting no `subprocess`/network/git/QEMU code path exists in any non-test module of the package (catalog, runtimes, certification), plus the M4/M5/L1/L2/L3 negative checks. |
| `test_os_lab_catalog.py` | 73 catalog/lifecycle checks (sibling cluster; `run()` + `test_os_lab_catalog()` like its siblings — no SystemExit at import), including the H1/M1 negative checks and the `EXECUTED`-ledger gate. |
| `test_certification.py` | 58 pipeline/scanner checks over the fixtures (pytest-discoverable): typed/ordered steps, report template, bounded verdict + forbidden-literal grep, every §143 fixture escalates its step, repo-wide sweeps, no-execution/read-only source scan, redaction, frozen report, symlink/forbidden/oversize walk (M2/M3), core-table single base (M6), catalog coordination. |

Run (from `backend/`; each file is also a plain script):
`cd backend && PYTHONPATH=/path/to/worktree/backend:/path/to/worktree DATABASE_URL=postgresql://u:p@localhost:5432/x python3 -m app.services.holding.os_lab.test_os_lab_runtimes` (likewise `test_os_lab_catalog`, `test_certification`), or `python3 -m pytest -q app/services/holding/os_lab` (3 collected, all pass).

---

## 1. Design

### Catalog-first (§113/§115)
Every entry starts `DISCOVERED` / trust `UNTRUSTED` / every upstream fact `UNVERIFIED`. `canonical_source` is **operator-stated upstream, NOT fetched, UNVERIFIED** — a note, not a verified fact (`upstream_status=UNVERIFIED`), confirmed only at `SOURCE_VERIFIED`. State moves only along one explicit chain, every transition is audited with evidence, and there is no code path from README/repo text to state:

`DISCOVERED → SOURCE_VERIFIED → PINNED (full 40-hex SHA) → QUARANTINED → STATIC_REVIEW → BUILD_REVIEW → ISOLATED_EXECUTION → SECURITY_REVIEW → CERTIFIED | RESTRICTED | REJECTED`

- `REJECTED` is reachable from every non-terminal state (fail-closed always available).
- Only `operator`/`kai` may transition; only the **operator** may adopt (`CERTIFIED`/`RESTRICTED`) — no self-approval (§0 #11).
- **A review state needs the reviewed thing to have happened:** `BUILD_REVIEW` is refused while `runtimes.EXECUTED["build"]` is False and `ISOLATED_EXECUTION` while `EXECUTED["qemu_boot"]` is False — for every actor. With the real (all-False) ledger the chain stops at `STATIC_REVIEW`; the tests simulate a later phase's ledger only inside a restoring context manager.
- Adoption (`CERTIFIED` *and* `RESTRICTED`) additionally requires the §114 verdict `NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE`, recorded only in `SECURITY_REVIEW` with its report as evidence.
- **`record_verdict` has a fail-closed direction:** `kai` may record only `SUSPICIOUS` / `REJECTED` / `UNVERIFIED`; the clean-scope verdict is **operator-only** (`PermissionError` otherwise). For *any* verdict, an attached report carrying its own `verdict` must agree ("recorded verdict contradicts the attached report"). The clean verdict further requires `scope == FULL` and no step left `SKIPPED` / `PENDING` / `UNVERIFIED` — a `STATIC_ONLY` report can never certify.
- Adoption requires a §117 `GapJustification` (concrete gap, why existing certified runtimes are insufficient, ≥1 alternative) — no runtime explosion. `justify_adoption` is **operator-only** (`actor` is keyword-only; kai / readme / `os_lab:*` get `PermissionError` and nothing is recorded).

### Verdict vocabulary (§114/§41)
`UNVERIFIED` · `NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE` · `SUSPICIOUS` · `REJECTED`. **`MALWARE_FREE` / `SAFE` / `CLEAN` do not exist** and are rejected at construction (`UltronSandboxRecord.__post_init__`).

### Runtimes bind to the catalog (§41)
`runtimes.catalog_binding()` resolves each runtime to its catalog entry and derives `install_allowed` via `install_gate(entry)`: **ADOPTED state + §114 verdict + §117 justification, all three, else refused with named reasons.** `install_gate` is the derivation; the runtime records (`ULTRON.installed`, `RestrictedRuntime.installed`) carry a constant `False` in this phase and are never set from it. The binding also reports `source_consistent` — the source each runtime record carries must equal the catalog's `canonical_source` (**one spine**; drift is visible, never silent). Today: all three `install_allowed=False` (3 reasons each), `source_consistent=True`.

### Flags (§102/§151)
`KAI_OS_LAB_ENABLED`, `KAI_OS_LAB_ULTRON_RUNTIME_ENABLED`, `KAI_OS_LAB_VIRTME_NG_ENABLED`, `KAI_OS_LAB_SYZKALLER_ENABLED` — **deliberately NOT declared in `app/config.py`** (a test asserts this): `getattr(settings, flag, False)` is False everywhere. A runtime is ON only if `not production AND master flag AND own flag`; **production stays DISABLED regardless of flags.** `_is_production` fails closed: `APP_ENV` (trimmed, lower-cased) is non-production only if it is one of `development / dev / local / test / staging` — absent, empty, `None`, `prod`, `stage`, `qa` are all production. Even ON never means "runs": `can_run()` also needs `installed` + manifest `selectable()` + a policy ALLOW — none of which is true in this phase.

---

## 2. §116 starting dispositions (catalog) — all DISCOVERED / UNTRUSTED / UNVERIFIED

| Entry | Category | Disposition | Starting risk (lab policy, not an upstream fact) | Note |
|---|---|---|---|---|
| Ultron OS | EDUCATIONAL_REFERENCE | EDUCATIONAL_SANDBOX | HIGH | §40 isolated QEMU only, production=NO. Small-author repo — provenance/license/activity UNVERIFIED. |
| virtme-ng | RESTRICTED_SECURITY_LAB | RESTRICTED_KERNEL_TEST_CANDIDATE | RESTRICTED | §42 default OFF, prod DISABLED. |
| Bottlerocket | INFRA_CANDIDATE | INFRA_CANDIDATE | MEDIUM | Container-host candidate; not selected for anything. |
| Qubes OS | SECURITY_REFERENCE | SECURITY_REFERENCE | LOW | §44 compartmentalization principles — read, never executed. |
| Genode | SECURITY_REFERENCE | SECURITY_REFERENCE | LOW | §44 capability-based OS principles — read, never executed. |
| Unikraft | SANDBOX_RUNTIME | EXPERIMENTAL_RUNTIME | HIGH | Adoption gated by §117. |
| Nanos | SANDBOX_RUNTIME | EXPERIMENTAL_RUNTIME | HIGH | Adoption gated by §117. |
| Hermit | SANDBOX_RUNTIME | EXPERIMENTAL_RUNTIME | HIGH | Upstream org/repo renamed historically — SOURCE_VERIFIED must confirm the path. |
| syzkaller | RESTRICTED_SECURITY_LAB | RESTRICTED_SECURITY_LAB | RESTRICTED | §43 disposable isolated VM only, heavy operator authorization. |
| Linux | PRODUCTION_PLATFORM | PRODUCTION_PLATFORM + KNOWLEDGE_REFERENCE | LOW | Catalog entry ≠ a re-certification of prod. |
| FreeBSD | KNOWLEDGE_PACK | KNOWLEDGE_REFERENCE | LOW | Knowledge only. |

`production_eligible` is derived (CERTIFIED + platform/infra category) and **nothing is ever auto-selected into production** — selection is a separate operator act (§40/§116).

---

## 3. The three governed runtimes (`runtimes.py`)

### §40 Ultron OS — `EDUCATIONAL_OS_SANDBOX`
Dashboard record `ULTRON`: `source` is read from the catalog's operator-stated `canonical_source` (`https://github.com/aswinmohanme/ultronOS` — **one spine**, not fetched, `source_note` says operator-stated/unverified; confirmed only at SOURCE_VERIFIED), and **all nine verification fields UNVERIFIED** — `pinned_sha, license, build_status, static_scan, qemu_boot_status, network_state, risk, last_verified, malware_scan`; `production_use=NO`; `installed=False`; `trust=UNTRUSTED`. `__post_init__` refuses a forbidden claim on **every** verification field in **any spelling**: the value is normalized (`[\s-]+ → _`, upper-cased) and rejected if any `_`-token is in `FORBIDDEN_CLAIMS` (`MALWARE_FREE / SAFE / VERIFIED_SAFE / CLEAN`) or `MALWARE_FREE` is a substring — so `malware free`, `Verified-Safe`, `clean `, `safe_2026`, `not safe` all fail construction.
Encoded constraints (`SandboxConstraints`, policy for the *future* gated run): `ISOLATED_QEMU_OR_CONTAINER_ONLY`, `credentials_allowed=False`, `host_fs_access=BOUNDED_WORKSPACE_ONLY`, `production_network_allowed=False`, `network_default=NONE`.

### §42 virtme-ng — `MCP` / `RESTRICTED_KERNEL_TEST_RUNTIME`
Manifest: `availability=DISCOVERED`, `activation=DISABLED`, `risk_class=RESTRICTED`, `HIGH_IMPACT`, tier 3, `sandbox_required`, `operator_approval_required`, `automatic_activation_allowed=False`, `selectable()==False`. Provenance is a **note** (`verified=False`, license/ref UNVERIFIED, `install_method=NONE_YET`). `installed=False` until `install_precondition=SUPPLY_CHAIN_CERT_PASS`.
Typed default-deny policy (`KernelTestPolicy.decide`):

| allow (bounded, isolated VM only) | deny (never, under any flag) |
|---|---|
| BOUNDED_KERNEL_BUILD · ISOLATED_VM_BOOT · KERNEL_TEST_RUN · DMESG_READ · KERNEL_COMPARISON | HOST_KERNEL_REPLACEMENT · PRODUCTION_REBOOT · HOST_ARBITRARY_SHELL · PRODUCTION_MODULE_LOAD · CREDENTIAL_ACCESS |

Unknown op → `DENIED_UNKNOWN_OP`. An op cannot be both allowed and denied (construction error). **The deny column is an invariant, `KERNEL_DENY`:** `__post_init__` asserts `deny ⊇ KERNEL_DENY` and `allow ∩ KERNEL_DENY = ∅` (a "permissive" policy that allows `HOST_ARBITRARY_SHELL` refuses to construct), and `decide()` checks `KERNEL_DENY` *before* any instance state — even a policy whose frozen fields are forced permissive still returns `DENIED` for every one of the five.

### §43 syzkaller — `RESTRICTED_SECURITY_LAB`
Manifest: `SECURITY_EXECUTION_FRAMEWORK`, `availability=DISABLED`, `activation=DISABLED`, `RESTRICTED`/`DESTRUCTIVE`, tier 4, `target_allowlist_required`, **`selectable()==False`, `automatic_activation_allowed==False` — never auto-selected, never production.**
`SecurityLabPolicy.admit(mission)` is typed admission of an *explicit authorized security|testing mission* (`authorized is True`, `operator_approval_ref`, `target_kind=ISOLATED_DISPOSABLE_VM`, no host/production target, no prod credentials/network). The best possible outcome is `ADMISSIBLE_NOT_RUNNABLE`; `can_run()` is always False in this phase (no allow-list exists for it yet).

---

## 4. §165 — KAI remains the brain: `OsLabAuthorityGuard`
No OS/runtime is ever an authority plane. `GUARD.check(AuthorityClaim(source, action))`:
- OS-lab source — the claim's `source` is normalized (strip / lower / `-` and whitespace → `_`) and matched against the runtime ids (`ultron_os`, `virtme_ng`, `syzkaller`), the normalized display names (`Ultron OS` → `ultron_os`), and any `os_lab` prefix, so `SYZKALLER`, ` syzkaller `, `OS_LAB:ultron`, `os-lab:ultron`, `virtme-ng`, `Ultron OS` all count — + any `AUTHORITY_ACTIONS` member (`GRANT_AUTHORITY, APPROVE, APPROVE_MERGE, APPROVE_DEPLOY, APPROVE_FINANCIAL, REWRITE_GOVERNANCE, SET_POLICY, ENABLE_FLAG, ESCALATE_ROLE, EXECUTE_ON_HOST, AUTO_SELECT_RUNTIME`) → `REJECTED`; `enforce()` raises `OsLabAuthorityViolation(PermissionError)`.
- OS-lab source + `PROVIDE_EVIDENCE / REPORT_RESULT / REPORT_LOG / REPORT_METRIC` → `EVIDENCE_ONLY` (its output is data).
- Anything else from an OS-lab source → `REJECTED_UNKNOWN_ACTION` (fail closed).
- Non-OS principals → `NOT_OS_LAB_SOURCE` (governed by the existing seams: `require_kai_ultra`, `kai_bridge`, governance actions).

Also enforced structurally: catalog entries carry **no** `permissions/action_class/activation/authority` field and report `authority_plane="KAI"`; runtime manifests' `permissions` are ceilings the governance layer enforces, never grants.

**Not yet wired:** the guard is a library invariant with tests; consulting it from the approval/governance seams is a follow-up in those files (out of this phase's new-files-only scope).

---

## 5. §102/§150 feature-registry rows (`os_lab_feature_registry`, additive)
Same shape as `holding_deployment.Feature.record()` + `installed/disposition/verification/production_use`; `holding_deployment.FEATURE_REGISTRY` itself is untouched (a test asserts this). Callers concatenate.

| feature_id | risk | state today |
|---|---|---|
| `os_lab` | P2 | DEPLOYED (code present) · runtime OFF · installed=True (framework) · verification SELF_TEST |
| `os_lab_ultron_sandbox` | P2 | cataloged · UNVERIFIED · installed=False · runtime OFF |
| `os_lab_virtme_ng` | P2 | candidate · NOT_INSTALLED (supply-chain cert PENDING) · runtime OFF |
| `os_lab_syzkaller` | P3 | RESTRICTED · never auto-selected · installed=False · runtime OFF |

`runtime_enabled` is False with flags absent and **still False in production with every flag on**.

---

## 6. What is and is NOT built / run in this phase

**Built (metadata + policy + tests):** catalog + lifecycle + §117 gate + verdict vocab; the three runtime records/policies; the §165 guard; the install gate + catalog binding; feature rows; `os_lab_view` assembly; the certification pipeline definition + static-only runner + §143 fixtures; 216 checks across three test files (73 catalog · 85 runtimes · 58 certification), including a negative test for every adversarial-review finding (H1, M1–M6, L1–L3).

**NOT built:** pipeline *execution* (pin-SHA fetch → isolated build → QEMU boot → monitor) — `certification.py` defines the steps and report shape but every executable step is `EXECUTION_GATED`; router/dashboard wiring (`core/api.py`, `frontend/admin/*` untouched); wiring of the guard into approval seams; any config flag.

**NOT run (by construction — `EXECUTED` ledger all False, static scan enforces no code path):** no clone, download, install, build, QEMU boot, network fetch, or new dependency. No upstream URL was fetched; no license/SHA/maturity was looked up.

**Next gated step (operator + isolated infra required):** SOURCE_VERIFIED (operator-confirmed URL, evidence `verified_at`) → PINNED (full SHA) → QUARANTINED → STATIC_REVIEW → BUILD_REVIEW → ISOLATED_EXECUTION → SECURITY_REVIEW (verdict) → operator adoption with a §117 justification. Only then does `install_gate` open; runtime flags stay a separate explicit enable, and production remains DISABLED.

## 7. §41/§114 supply-chain certification pipeline + §143 fixtures (`certification.py`)

**One ordered pipeline (`PIPELINE`, 26 frozen `StepDef`s; position = order).** Each step is `STATIC` (a named pure check over the supplied inventory — runnable now) or gated (`BUILD` / `EXECUTION` / `ARTIFACT` — declares what it *will* observe, has no check, never runs here).

| # | step | phase | what the static check decides from the inventory alone |
|---|---|---|---|
| 1 | `canonical_upstream` | STATIC | supplied origin vs the catalog's `canonical_source` (`.git`/slash/case-normalized); PASS only with §113 `source_verified_at` evidence, else UNVERIFIED; mismatch → HIGH |
| 2 | `pin_sha` | STATIC | full 40-hex commit SHA (§41) or FAIL; none supplied → UNVERIFIED |
| 3 | `license` | STATIC | LICENSE/COPYING present (else MEDIUM); identifier stated or UNVERIFIED |
| 4 | `file_inventory` | STATIC | every file has a path + a sha256 of its **whole** content; anything the walk recorded but did not read (symlink not followed / §30 forbidden target not opened / oversize not opened) → UNVERIFIED with a LOW finding per file — never PASS on an incomplete inventory |
| 5–7 | `submodules`, `git_lfs`, `binary_blobs` | STATIC | submodules/LFS = content outside the inventory → UNVERIFIED; executable binaries MEDIUM, media LOW, oversize (not opened) MEDIUM |
| 8–9 | `package_manifests`, `install_hooks` | STATIC | manifest without lockfile; `pre/postinstall` / `cmdclass` hooks |
| 10–13 | `build_scripts`, `dockerfiles`, `ci_workflows`, `shell_scripts` | STATIC | inventoried (+ OS-lab extras: `ADD https://` / archive downloads in Dockerfiles, `pull_request_target` / `${{ secrets.` in CI); the generic malicious patterns are applied to these files repo-wide by steps 14–20 — no second copy |
| 14–20 | `network_destinations`, `telemetry`, `privileged_ops`, `credential_reads`, `persistence`, `downloaded_binaries`, `obfuscation` | STATIC | **repo-wide** sweeps over every non-doc text file. Generic malicious patterns (reverse shells, pipe-to-shell, `rm -rf /` / `dd` / `mkfs`, AWS keys, RSA/EC key headers, eval+base64, shell injection …) come from **`core.security_scanner._COMPILED_PATTERNS` — one pattern, one severity, routed by description to the owning step**; only OS-lab-specific categories are local (bare `nc -e`, unexpected outbound hosts vs `KNOWN_REGISTRY_HOSTS` + declared `expected_hosts`, telemetry SDKs, sudo/setuid/`--privileged`/module load, credential *paths*, non-RSA/EC key headers, cron/systemd/rc persistence, downloaded archives, atob/compile/charcode/hex obfuscation, long base64 blobs). Credential *material* is swept over **all** text files, docs included — a private key in a `.txt`/`.md` is still a private key. |
| 21 | `isolated_build` | BUILD | gated — observes `build_log_digest, toolchain, exit_status` |
| 22 | `restricted_network` | EXECUTION | gated — `egress_policy, attempted_destinations` |
| 23 | `qemu_vm_exec` | EXECUTION | gated — `image_digest, boot_status, snapshot_discarded` |
| 24 | `resource_monitoring` | EXECUTION | gated — `cpu_peak, ram_peak_mb, disk_delta_mb, io_bytes` |
| 25 | `dynamic_behavior` | EXECUTION | gated — `fs_mutations, network_attempts, process_tree, persistence_attempts, credential_access` |
| 26 | `artifact_inspection` | ARTIFACT | gated — `artifact_digests, unexpected_artifacts, embedded_binaries` |

**Step status vocabulary:** `PENDING / PASS / FAIL / SKIPPED / UNVERIFIED`. `new_report()` is the template — every step PENDING, verdict UNVERIFIED, `scope=NOT_RUN`, `executed` = `runtimes.EXECUTED` (all False), `authority_plane=KAI` (§165: a report is evidence, never an authority). `run_static(inventory)` runs steps 1–20 in order and marks 21–26 `SKIPPED` with note `EXECUTION_GATED`; `scope=STATIC_ONLY`. **`CertificationReport` and `StepResult` are frozen dataclasses and `steps` is a tuple** — a STATIC_ONLY report cannot be flipped to FULL/PASS in place (tested), and `catalog.record_verdict` refuses a clean verdict whose report is not `scope=FULL` with every step decided.

**Pattern base.** `core.security_scanner._COMPILED_PATTERNS` is imported once at module top inside `try`; if it is unavailable, every core-backed step (`network_destinations`, `downloaded_binaries`, `credential_reads`, `privileged_ops`, `obfuscation`) reports `UNVERIFIED` with the reason `core scanner table unavailable` — never a silent "built-in only" sweep (tested by nulling the table). Local OS-lab findings still surface in that mode and local HIGHs still REJECT.

**Finding severities** reuse `security.models.Severity` values (`INFO/LOW/MEDIUM/HIGH/CRITICAL`). ≥MEDIUM fails its step; a finding snippet carries 20 chars *before* the match and **nothing after it** (a matched key header never drags its key body into the report), then passes through the shared `task_resolver.redact` (a scanned AWS key is *flagged* at core's severity — MEDIUM → `credential_reads` FAIL → `SUSPICIOUS` — but never appears in the JSON report — tested).

**Verdict (bounded, deterministic — `derive_verdict`):** any HIGH/CRITICAL finding → `REJECTED`; any FAIL → `SUSPICIOUS`; every step PASS (*including the gated ones*) → `NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE`; anything PENDING/SKIPPED/UNVERIFIED → `UNVERIFIED`. Because steps 21–26 are always SKIPPED in this phase, **a static-only run can never reach the clean-scope verdict** — an all-clean, fully-evidenced inventory still reports `UNVERIFIED`. "MALWARE_FREE" / "ABSOLUTELY SAFE" are asserted absent from the module and fixtures. A report cannot self-certify: `catalog.record_verdict` refuses outside `SECURITY_REVIEW`; a REJECTED static report drives `STATIC_REVIEW → REJECTED` via the audited `catalog.advance` with the report as evidence.

**Inventory is supplied, never fetched.** `RepoInventory` is built in memory or by `inventory_from_dir()` — a read-only walk of a local directory the operator already has. The walk: consumes `rglob` lazily (capped by `max_files`, sorted afterwards); skips dotfiles except CI/submodule/LFS/package-registry configs **and except §30 forbidden targets** (a shipped `.env` / `.aws/credentials` is reported, not hidden); **records symlinks (file or dir) but never follows them** (content `''`, no digest, `skipped=symlink`); asserts every path resolves under the root; **never opens** a `task_resolver.is_forbidden_repo_target` path (`skipped=forbidden` → `credential_reads` MEDIUM "shipped in the repo — not opened") or a file larger than `_MAX_READ` (1 MB: `stat` only, `sha256=None`, `skipped=truncated` — a prefix digest is never recorded as the file's digest; tested with an unreadable oversize file). Files ≤ `_MAX_READ` are read and hashed in full. No `subprocess`/`socket`/`urllib`/`http`/`requests`/`git` import, no `open(`/write/mkdir/unlink/chmod call (all asserted by tests).

**§143 fixtures** (`fixtures/mimic_repo/`, canonical source `https://example.invalid/os-lab/mimic-repo` — RFC 2606 reserved): running `run_static(fixture_inventory())` yields FAIL with a ≥MEDIUM finding on exactly the expected step for every fixture (`FIXTURE_EXPECT`), HIGH for pipe-to-shell / credential path / persistence, and verdict `REJECTED`.

**Not built (next gated step):** executing steps 21–26 needs isolated infra + the supply-chain cert itself; `evidence_bus` wiring of reports as security evidence; router/dashboard surface.

## 8. Open items for the operator
1. **Ultron canonical source.** There is ONE value: `catalog.py` records `https://github.com/aswinmohanme/ultronOS` as the **operator-stated** upstream (NOT fetched, UNVERIFIED) and `runtimes.ULTRON.source` reads that same catalog value (`catalog_binding().source_consistent` pins them equal). Several projects carry the name "Ultron", so `SOURCE_VERIFIED` must confirm this URL with `verified_at` evidence — until then nothing may read it as verified.
2. Hermit's upstream path needs confirmation at SOURCE_VERIFIED (historic rename).
3. Whether the OS Lab is in scope at all remains the baseline's Phase-10 question; this phase only makes the framework honest and dark.
