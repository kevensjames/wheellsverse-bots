# KAI SWE Runtime (sandboxed code execution)

Integration #3 of the audit program — the **secured execution envelope** for
software-engineering tasks. KAI deliberately exposes no shell/code-exec to its
agents; this widens that trust boundary **only** through a locked-down, disposable
container, operator-triggered and approval-gated. See
`plans/PLAN-kai-software-engineering-runtime.md` (audit branch) for the full plan.

## What this increment delivers
The **security primitive + control plane**, feature-flagged OFF:
- `DockerSandbox` — runs a bounded command in a throwaway container: **no host
  bind mount** (source is `docker cp`'d in, artifacts copied out), `--network
  none`, `--cap-drop ALL`, `--security-opt no-new-privileges`, resource caps
  (memory/pids/cpu), wall-clock timeout (docker kill), `docker rm -f` afterward.
- `AgentRuntime` seam (`SandboxCommandRuntime`) — the OpenHands autonomous agent
  brain plugs in here later, running its steps through the SAME envelope.
- `POST /admin/swe/run` — operator-only, `@audited(scope="swe.run",
  destructive=True)` + `approved=true`, gated by `KAI_SWE_RUNTIME_ENABLED` + a
  source-dir allowlist. Returns the produced artifacts (the diffable patch) + logs.

## What it does NOT do (deliberately, by plan)
- No autonomous planning yet (the OpenHands brain is the next increment).
- No auto-merge, no auto-deploy — a human reviews the produced patch out of band.
- Not exposed as an LLM tool. Not enabled on the production daemon.

## Security model
- **Isolation**: no network, no host filesystem exposure (cp-in/cp-out), all
  Linux capabilities dropped, no-new-privileges, no host Docker socket, resource
  caps, wall-clock timeout, ephemeral (force-removed).
- **Policy**: image allowlist + command denylist (egress/credential tokens) +
  source-dir allowlist (deny-by-default).
- **Governance**: scope opt-in (`KAI_SCOPE_SWE_RUN`) + `approved=true` + audit on
  every run.
- **Kill switch**: `KAI_SWE_RUNTIME_ENABLED=0` → the backend is `DisabledSandbox`
  (executes nothing).

## Hardening follow-ups (documented, not in this increment)
- Run as a non-root user inside the container (needs a chown-on-entry entrypoint).
- microVM (Firecracker/gVisor) backend behind the same `SandboxBackend` interface.
- Task persistence (swe_tasks table) + a stateful approve-before-push-to-branch
  workflow + the OpenHands agent brain.
- Per-tenant sandboxes + budgets when moved beyond single-operator use.

## Config
See `.env.example` (`KAI_SWE_*`). Requires Docker on the runner. The image in the
allowlist must be pulled/cached (`--pull never`).

## Tests
`tests/services/swe_runtime/` — policy + flag gating (deterministic) and a real
container integration test (skipped when Docker/the image is unavailable):
network is cut, source is edited on a disposable copy, artifacts captured,
timeout kills, DisabledSandbox when the flag is off.
