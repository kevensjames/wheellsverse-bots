# KAI Capability Execution V1 — Deploy Bundle (§17)

Exact, operator-run deployment for the certified execution gateway. **`railway up` / `git push` are
classifier-gated to the operator** — Claude prepared + certified everything below but does not run them.
Money mode stays MOCK. Deploy App B with the flag **OFF** first, smoke, then enable.

## Source (certified)
| what | branch | SHA |
|---|---|---|
| Fabric (source of truth) | `feat/kai-capability-fabric` | `3dc0d1b` |
| **App B integration (deploy this)** | `feat/kai-exec-appb-integration` | `56dc6a2` (merge of fabric into holding-os) |
| App B rollback (current prod) | `feature/kai-holding-operations-os` | `914855d` |
| App A deploy branch | `production` | `e9988c5` (rollback target) |

Merge conflicts resolved (§11, kept both sides): `config.py` (holding flags **+** `KAI_CAPABILITY_EXECUTION_ENABLED`),
`kai_bridge.py` (`allow_prefixes` = …+`holding`+`capabilities`). Holding code diff = **0 lines** (preserved).

## Certification (all green, this integration branch)
- capability suite 13 files / 173 tests · Nexus JS 16 · bridge 27 · holding-registry 9/9 · reasoning-sanitizer 26
- real `app.main:app`: flag **OFF → 0** `/admin/capabilities` routes · flag **ON → 6** routes
- No arbitrary shell · 0 financial exec · 0 restricted runtimes · MONEY_MODE=MOCK

## STEP 1 — Deploy App B (kai-prod), flag OFF (§18)
From the worktree LINKED to the `kai-production` Railway project (the scratchpad `kai-prod-deploy`
worktree, or re-link one), check out the integration branch and deploy:
```bash
cd <kai-production-linked-worktree>
git fetch && git checkout feat/kai-exec-appb-integration   # 56dc6a2
railway status                                             # confirm project=kai-production, service=kai-prod
railway up --service kai-prod --detach
```
Wait for **SUCCESS**; confirm health `env=production status=ok`, replicas healthy, 0 crash loop.

## STEP 2 — Flag-OFF smoke (§19) — proves the safety latch in prod
```bash
BASE=https://kai-prod-production.up.railway.app
curl -s -o /dev/null -w "%{http_code}\n" $BASE/admin/capabilities        # expect 404 (routes NOT mounted, flag off)
```
404 with the flag off proves the latch. (Owner-auth needed once mounted.)

## STEP 3 — Enable execution (§22–23)
```bash
railway variables --set KAI_CAPABILITY_EXECUTION_ENABLED=true --service kai-prod
railway up --service kai-prod --detach   # if a redeploy is needed to pick up the var
```
Do **NOT** change `MONEY_MODE` (stays MOCK). Do not enable any restricted runtime.

## STEP 4 — First real production execution (§24) — yt-dlp metadata (read-only)
Owner-authorized, via the bridge from App A (or directly to App B with an owner session):
```bash
curl -s -X POST $BASE/admin/capabilities/yt-dlp/invoke \
  -H 'Content-Type: application/json' -H "<owner session cookie/x-admin-token>" \
  -d '{"operation":"metadata","input":{"url":"https://archive.org/details/BigBuckBunny_124"}}'
# expect: status OK, evidence.title="Big Buck Bunny", provenance REAL, NO download
curl ... -d '{"operation":"download","input":{"url":"https://archive.org/details/BigBuckBunny_124"}}'
# expect: status OPERATION_NOT_ENABLED (403)
```

## STEP 5 — App A (bridge + Nexus) — separate deploy (§15/§20)
App A (app.wheellsverse.com) runs `core/kai_bridge.py` (the proxy) + serves the Nexus. It needs the
bridge change (`capabilities` prefix, owner-only) so `/admin/kai/capabilities/*` reaches App B.
**Pending before App A delivers the UI:** the live page `kai-capabilities.html` must be wired to the
execution endpoints (the tested `kai-nexus-capabilities.js` execution layer). Bridge is ready; page
wiring is the remaining App-A-side glue. Merge bridge+frontend into `production`, then the git-connected
App A deploy picks it up.

## ROLLBACK (§41)
1. `railway variables --set KAI_CAPABILITY_EXECUTION_ENABLED=false --service kai-prod` (instant latch off)
2. redeploy if needed
3. App B code rollback: check out `feature/kai-holding-operations-os` (914855d) + `railway up`
4. App A rollback: revert `production` to `e9988c5`

## What is NOT in this deploy
Restricted security runtimes (Empire/Strix/reverse-skill active/SecLists/Payloads) — catalog-only.
Financial execution — OFF. codebase-memory-mcp — EXTERNAL_BLOCKED in prod (no binary/index). MarkItDown —
fixture-only (USER_FILE_INPUT_PENDING).
