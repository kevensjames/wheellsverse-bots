# Isolated deterministic browser worker (Section 7) — milestone PASS

The first real KAI execution worker: **deterministic Playwright in an isolated container** — no model,
no AI, no credential (Section 1 prefers deterministic browser automation over AI). Achieves the mission's
first-milestone shape: KAI submits an approved read-only browser task → isolated worker runs it → structured
evidence → cancellable → policy-gated.

## Files
- `Dockerfile` — pinned `mcr.microsoft.com/playwright/python:v1.47.0-jammy` + `playwright==1.47.0`, non-root (`pwuser`).
- `runner.py` — in-container task runner; read-only actions only; refuses WRITE even if the host policy is bypassed;
  blocks internal/metadata/private hosts; requires a domain allowlist; returns structured JSON evidence.
- `submit.py` — host-side seam: policy gate (mirrors `backend/app/services/tars/policy.py`) + `docker run` with strong
  isolation; timeout + `cancel()`.
- `cert.py` — milestone certification (6/6).

## Isolation applied (colima/docker)
`--read-only` rootfs · `--tmpfs /tmp` only · `--user pwuser` (non-root) · `--cap-drop ALL` · `--security-opt
no-new-privileges` · `--memory 1g --cpus 1 --pids-limit 256` · **no host mounts** (no repo/.env/SSH/docker-socket) ·
`--rm` ephemeral per task · in-code domain allowlist + internal/metadata/private-host block.

## Milestone result (6/6)
read-only task executes + evidence · WRITE denied (host policy) · prohibited denied · runner defense-in-depth ·
cancellation kills a running container.

## Honest remaining hardening (before this is production-eligible)
- **Network egress default-deny** — a container on the default bridge can still reach arbitrary hosts; the in-code
  allowlist blocks navigation but not a compromised runner's raw calls. Full Section-9 compliance needs an
  **egress-proxy/firewall sidecar** (allowlist at the network layer). NOT done.
- **Worker attestation → Capability Fabric** — wire this worker's health/attestation into the TARS adapter so the
  `computer_use`/`browser` capability derives READY only when a certified worker is online (the foundation exists on
  `feature/kai-tars-execution-worker`).
- **Approval-bound WRITE path** — WRITE actions are currently denied; the approval-gated write flow (bound approval →
  container form-fill with preview + pause) is a later increment.
- Runs on a local colima container; a hosted deployment + per-user isolation is a later phase.

## Run
```
cd ops/browser-worker
docker build -t wv-browser-worker:v1.47.0 .        # requires docker/colima running
python3 cert.py                                     # milestone certification
```

## Removal
`docker rmi wv-browser-worker:v1.47.0` · delete `ops/browser-worker/`.
