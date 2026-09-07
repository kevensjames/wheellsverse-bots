# Production verifier credential — plan only, nothing written

**No production variable has been written.** This records what to write, where, and why, so the owner
can execute it deliberately.

---

## 1. The variable

| Field | Value |
|---|---|
| Name | `RELEASE_VERIFIER_SIGNING_SECRET` |
| Services | `wheellsverse-v2` (App A) **and** `kai-prod` (App B) — must be the **same value** on both, since App A verifies the token and App B re-verifies it independently |
| Value | 64 hex characters from a CSPRNG (`secrets.token_hex(32)`) |
| Storage | Railway service variables only |
| Rotation | Independent of every other secret. Rotating it invalidates outstanding verifier tokens and nothing else. |

## 2. What it must NOT be

- **Not** the owner `API_KEY`. That is the whole point of the role.
- **Not** `SESSION_SIGNING_SECRET`. Signing verifier tokens with the session secret would mean anything
  able to mint a verifier identity could also mint an **owner session**, which destroys the separation.
- **Not** the staging value. Staging currently holds fingerprint `6b35a2510aaf4af9`, where the
  fingerprint is `sha256(value)[:16]` — recomputed from Railway at certification time, and verifiable
  with that method. (An earlier draft of this document recorded `3a91becc76354efb`. That value does not
  reproduce from the current staging secret under sha256, sha1, md5 or blake2b, so it was either
  superseded by a later rotation or simply wrong; it is corrected here rather than carried forward.)
  Production must get its own value regardless — a shared secret would let a staging token act
  against production.
- **Not** committed, printed, or pasted into any transcript.

## 3. Authority this grants

Read only, and narrowly:

| Surface | Verifier |
|---|---|
| `/admin/registry.json`, `/admin/capabilities.json`, `/admin/command/metrics.json` | **200** — read |
| approve, execute, defer, deploy, finance, messaging, policy, authority | **403** at App B's `require_can_act` |
| Minting an execution confirmation | **403** — `CONFIRMATION_REQUIRES_OWNER` |
| App A → App B bridge (consequential POSTs) | **401** at the bridge — it authenticates on session, and a verifier token is not one |

It carries `read` and `verify` scopes and **no** write, high-impact, financial, destructive or ultra
scope. That is asserted in tests against `MUTATING_SCOPES`, not left to inspection.

## 4. The rule this exists to enforce

**Automated production verification must never possess the owner credential.**

The 2026-09-07 incident happened because reading protected admin surfaces required the owner key — the
only credential that could — and an owner credential can execute. Once this variable exists in
production, every automated smoke test and release verification run uses a verifier token, and the
owner key stops being a routine operational tool.

## 5. Suggested commands, for the owner to run

```bash
# generate — do not echo it
SEC=$(python3 -c "import secrets;print(secrets.token_hex(32))")

# App A
railway link --project 5407586d-e648-4dd1-a442-ea0f805f2e0e --service wheellsverse-v2 --environment production
railway variables --set "RELEASE_VERIFIER_SIGNING_SECRET=$SEC" --skip-deploys

# App B — the SAME value
railway link --project 896e8fbe-3daa-4a5c-8802-ff86e49e750e --service kai-prod --environment production
railway variables --set "RELEASE_VERIFIER_SIGNING_SECRET=$SEC" --skip-deploys

unset SEC
```

Both services need a redeploy or restart to pick it up. Until then, `_release_verifier_ok` returns
False and no verifier identity is accepted — **fail closed**, which is the correct behaviour for an
unconfigured environment.

## 6. Minting a token for a verification run

Server-side only, never in a client:

```python
from app.services.holding.verifier_role import mint_verifier_token
tok = mint_verifier_token(subject="ci-release-check", secret=<the production secret>, ttl_seconds=1800)
# send as the request header: x-kai-verifier-token
```

Short TTL by design — a verification run is minutes. The `subject` makes the run attributable.

## 7. Ordering

1. Owner approves PR #70.
2. Merge and deploy through the existing gate.
3. **Then** write this variable and redeploy, so the code that consumes it is already live.

Writing it before the code ships is harmless (nothing reads it) but pointless; writing it after keeps
the change auditable as one step.
