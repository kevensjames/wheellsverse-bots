# KAI Computer Operations — Phase 1 Discovery Record

Status: DISCOVERY COMPLETE (facts below are verified by direct observation, not assumption).
Recorded: 2026-09-08.

## 1. Execution host (verified, NOT assumed)

The mission required distinguishing the current development host from the intended
local server and the target desktop. Verified by direct inspection:

| Fact | Value | Evidence |
|---|---|---|
| Hostname | `Jhons-Mac-mini.local` | `uname -a` |
| Kernel | Darwin 25.6.0, `RELEASE_ARM64_T8132` | `uname -a` |
| CPU / RAM | Apple M4 / 16 GB | `sysctl machdep.cpu.brand_string`, `hw.memsize` |
| Free disk (internal `/`) | 73 GiB available of 228 GiB | `df -h /` |
| External volume | `/Volumes/Wheellsverse` 714 GiB free | `df -h` |
| Interactive GUI session | YES — console user `jhonwheeler`, session manager `Aqua` | `who`, `launchctl managername`, `stat -f %Su /dev/console` |

**Conclusion:** the development host, the intended local server, and the target desktop are
the SAME machine (the Mac mini M4). Desktop control is therefore physically possible here,
subject to macOS TCC permission grants. This was verified rather than assumed.

## 2. Runtimes present on host

| Tool | Version | Notes |
|---|---|---|
| node | v22.22.2 | satisfies harness `engines.node` `^22.19.0 \|\| >=24.0.0` |
| pnpm | **installed during this work** | was absent; activated via `corepack prepare pnpm@11.7.0 --activate` to match the harness `packageManager` pin exactly |
| python3 | 3.11.15 | |
| uv | 0.11.11 | |
| ollama | 0.33.3 | **running** and serving |
| docker / colima | installed but **daemon not running** | container isolation unavailable unless started |
| screencapture / osascript / sandbox-exec | present at `/usr/sbin`, `/usr/bin` | native macOS desktop + sandbox primitives |

## 3. Local model endpoint (LOCAL_ONLY candidate) — VERIFIED WORKING

`ollama` exposes an OpenAI-compatible API at `http://127.0.0.1:11434/v1`.

Verified live, no cloud request involved:

```
$ curl -s http://127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' \
   -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"Reply with exactly: LOCAL_OK"}],...}'
{"id":"chatcmpl-8", ... "message":{"role":"assistant","content":"LOCAL_OK"}, ...
 "usage":{"prompt_tokens":35,"completion_tokens":3,"total_tokens":38}}
```

Models available locally (`ollama list`): `llama3.1:8b` (4.9 GB), `qwen2.5:7b` (4.7 GB),
`llama3.2:latest` (2.0 GB), `nomic-embed-text:latest` (274 MB).

**No large model download is required** to demonstrate LOCAL_ONLY. Per the mission, no model
will be downloaded without hardware inspection and operator approval.

Note on the strength of this evidence: the transcript above proves only that ollama serves an
OpenAI-compatible endpoint. It hits ollama DIRECTLY and does not traverse the harness or its pi-ai
adapter, so on its own it does NOT establish that the harness can reach a local model. The
end-to-end proof is the ACP round trip recorded in `docs/computer-ops/10-EVIDENCE.md`, which drives
the pinned harness over ACP and gets an answer back from `qwen2.5:7b`.

## 4. macOS permission state (TCC) — read-only inspection

Existing `kTCCServiceAccessibility` grants belong to unrelated applications
(Claude for Desktop, Chrome Remote Desktop, Logi, OpenAI CUAService). **No KAI desktop
bridge is enrolled, and none of these grants are usable by KAI.**

Screen Recording and Accessibility for a KAI bridge are operator-granted through
System Settings; they cannot be, and will not be, set programmatically. This is a
recorded operator gate, not a defect.

## 5. Upstream pin (deepseek-ai/deepseek-harness)

| Field | Value |
|---|---|
| Repository | `https://github.com/deepseek-ai/deepseek-harness` |
| Pinned commit | `c389f96bf3a9b6807cb71ed6bdad5849be0df6d8` |
| Commit date | 2026-09-08T00:46:19+08:00 |
| Version | `0.1.3-alpha.2` (`package.json`) |
| Default branch | `master` |
| License | **MIT** (`LICENSE`, "Copyright (c) 2026 DeepSeek") |
| Language | TypeScript monorepo (pnpm workspaces) |
| Checkout location | `/Users/jhonwheeler/kai-harness-runtime/deepseek-harness` (OUTSIDE application source) |
| Toolchain required | `pnpm@11.7.0`, node `^22.19.0 \|\| >=24.0.0` |

### Upstream's own safety position (decisive for architecture)

`SAFETY.md` states verbatim:

> "DeepSeek Harness is experimental developer-preview software. It has not undergone a
> security audit and must not be treated as secure or production-ready."

> "Sandboxing, approval prompts, and permission controls can reduce risk, but they do not
> guarantee isolation or prevent damage."

> "Do not rely on DeepSeek Harness as the sole security control for untrusted workloads."

**Architectural consequence:** the harness CANNOT be the policy enforcement point. KAI must
enforce identity, scope, approvals, budgets and STOP *outside* the harness process, and must
treat all harness output as untrusted input. This is consistent with the existing KAI lesson
that scope must be enforced at every reachable entry point, not only at a bridge.

`README.md` additionally warns the project is in developer preview with
"COMPATIBILITY-BREAKING CHANGES" expected — reinforcing that the harness must remain a
*replaceable* execution provider behind a narrow adapter, never a load-bearing dependency.

## 6. KAI base branch selection

`origin/production` @ `073c9a4` is the branch that actually carries Holding Command:

- 158 files under `backend/app/services/holding/`
- `backend/app/routers/admin_holding.py`, `admin_holding_command.py`
- `frontend/admin/holding.html`, `kai-presence.js/.css`, `kai-nexus.*`, `kai-capabilities.html`
- `backend/alembic/versions/0007_add_holding_action_nonces.py` (approval nonce/replay infra)

Other candidate branches were checked and rejected as bases: `origin/main` has no holding
surface at all; `feat/kai-capability-fabric` has presence but no holding services;
`feature/kai-holding-operations-os` and `feat/kai-cyber-operations` are older/narrower supersets.

**Work branch:** `feat/kai-computer-operations`, created from `origin/production` @ `073c9a4`,
in an isolated worktree at `/Users/jhonwheeler/wheellsverse-kai-compute`.
Unrelated in-progress work on `feat/kai-freellmapi` (the `istanbul` worktree) is untouched.
No SOL payment flow is in scope.
