# Isolated GitHub read-only worker — cert PASS (7/7)

The second KAI execution worker, built on the browser worker's isolation + egress primitives.
Deterministic **read-only GitHub REST** (no model, no writes): KAI submits an approved read-only
task → isolated, egress-locked container hits `api.github.com` → structured evidence → policy-gated.
Feeds the Holding OS (PR/CI/issue state → briefing priorities).

## Files
- `Dockerfile` — `python:3.11-slim` + `PySocks`, non-root (`ghworker`). No browser needed.
- `runner.py` — in-container runner; read-only action allowlist (get_repo/list_prs/get_pr/list_issues/
  ci_status); refuses writes even if the host policy is bypassed; routes all traffic through the SOCKS5
  proxy (remote DNS via a `getaddrinfo` override); **never logs `GITHUB_TOKEN`** (scrubs every output).
- `submit.py` — host-side seam: policy gate (read-only allowed; writes need a bound approval;
  prohibited fail-closed) + strong isolation + `--internal` net + SOCKS5 egress proxy locked to
  `api.github.com`; injects a read-only token via env at run time (never baked, never logged).
- `cert.py` — certification (7/7).

## Isolation applied (colima/docker)
`--read-only` rootfs · `--tmpfs /tmp` (16m) · `--user ghworker` (non-root) · `--cap-drop ALL` ·
`--security-opt no-new-privileges` · `--memory 256m --cpus 0.5 --pids-limit 128` · **no host mounts** ·
`--rm` ephemeral · **`--internal` network (no direct egress); all traffic via the allowlist proxy
(api.github.com ONLY).**

## Cert result (7/7)
read-only `get_repo` executes egress-locked + evidence · WRITE denied (host policy) · prohibited denied ·
runner defense-in-depth (write refused in-container) · **egress default-deny** (proxy refuses
api.github.com when not allowlisted — SOCKS `0x02 Connection not allowed by ruleset`) ·
**`GITHUB_TOKEN` never appears in output.**

## Reuse note
The SOCKS5 egress-allowlist proxy (`../browser-worker/proxy`, image `wv-egress-proxy:v1`) is shared —
one hardened egress primitive, every worker inherits network default-deny. `urllib` gets remote DNS
via PySocks + a `getaddrinfo` override (the internal network has no local DNS).

## Run
```
cd ops/github-worker
docker build -t wv-github-worker:v1 .          # worker (requires docker/colima + wv-egress-proxy:v1)
python3 cert.py                                # certification (7/7)
```

## Removal
`docker rmi wv-github-worker:v1` · delete `ops/github-worker/`.
