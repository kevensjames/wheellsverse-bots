# Isolated deterministic browser worker (Section 7) — milestone PASS (7/7)

The first real KAI execution worker: **deterministic Playwright in an isolated container** — no model,
no AI, no credential (Section 1 prefers deterministic browser automation over AI). Achieves the mission's
first-milestone shape: KAI submits an approved read-only browser task → isolated worker runs it → structured
evidence → cancellable → policy-gated → **network egress default-deny (allowlist SOCKS5 proxy sidecar)**.

## Files
- `Dockerfile` — pinned `mcr.microsoft.com/playwright/python:v1.47.0-jammy` + `playwright==1.47.0`, non-root (`pwuser`).
- `runner.py` — in-container task runner; read-only actions only; refuses WRITE even if the host policy is bypassed;
  blocks internal/metadata/private hosts; requires a domain allowlist; routes all traffic through the egress proxy
  (forces remote DNS so the internal-network worker never resolves/reaches anything directly); returns JSON evidence.
- `submit.py` — host-side seam: policy gate (mirrors `backend/app/services/tars/policy.py`) + `docker run` with strong
  isolation; orchestrates the internal network + egress-proxy sidecar; timeout + `cancel()`.
- `proxy/` — **egress-allowlist SOCKS5 proxy sidecar** (stdlib-only, non-root). Default-DENY: permits CONNECT only to
  an exact host in `ALLOWED_DOMAINS` on port 443; refuses IP-literal targets, non-443 ports, internal/metadata hosts,
  and everything else. It is the ONLY path off the worker's internal network.
- `cert.py` — milestone certification (7/7).

## Isolation applied (colima/docker)
`--read-only` rootfs · `--tmpfs /tmp` only · `--user pwuser` (non-root) · `--cap-drop ALL` · `--security-opt
no-new-privileges` · `--memory 1g --cpus 1 --pids-limit 256` · **no host mounts** (no repo/.env/SSH/docker-socket) ·
`--rm` ephemeral per task · in-code domain allowlist + internal/metadata/private-host block ·
**worker on an `--internal` docker network (no direct internet); all egress forced through the allowlist proxy.**

## Milestone result (7/7)
read-only task executes + evidence (through the proxy) · WRITE denied (host policy) · prohibited denied · runner
defense-in-depth · cancellation kills a running container · **egress default-deny: proxy blocks a host the runner
would otherwise allow, at the network layer.**

## Egress topology
Worker runs on an `--internal` network with no route to the internet and no external DNS. The proxy sidecar is on
BOTH that internal network and the bridge, so it is the single egress path. Chromium is launched with
`--proxy-server=socks5://<proxy-ip>:8888` + `--host-resolver-rules=MAP * ~NOTFOUND,EXCLUDE <proxy-ip>`, which forces
**remote DNS** (the proxy resolves the target) and prevents any direct/local resolution. A compromised runner cannot
reach a non-allowlisted host because the network itself has no other way out.

## Honest remaining hardening (before this is production-eligible)
- **Worker attestation → Capability Fabric** — wire this worker's health/attestation into the TARS adapter so the
  `computer_use`/`browser` capability derives READY only when a certified worker is online (the foundation exists on
  `feature/kai-tars-execution-worker`).
- **Approval-bound WRITE path** — WRITE actions are currently denied; the approval-gated write flow (bound approval →
  container form-fill with preview + pause) is a later increment.
- Runs on a local colima container; a hosted deployment + per-user isolation is a later phase.

## Run
```
cd ops/browser-worker
docker build -t wv-browser-worker:v1.47.0 .        # worker (requires docker/colima running)
docker build -t wv-egress-proxy:v1 ./proxy         # egress-allowlist proxy sidecar
python3 cert.py                                     # milestone certification (7/7)
```

## Removal
`docker rmi wv-browser-worker:v1.47.0 wv-egress-proxy:v1` · delete `ops/browser-worker/`.
