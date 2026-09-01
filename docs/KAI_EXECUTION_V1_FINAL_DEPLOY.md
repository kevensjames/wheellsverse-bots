# KAI Capability Execution V1 — Final Synchronized Deploy (§21/§22)

Both apps built + certified. **`railway up`, `railway variables --set`, and `git push` are
classifier-gated to the operator** — everything below is prepared + verified; Claude does not run
production-mutating commands. Money mode stays MOCK. Deploy App B **flag OFF** first.

## Certified sources
| target | branch | SHA | worktree |
|---|---|---|---|
| **App B** (kai-prod backend) | `feat/kai-exec-appb-integration` | `82c1a53` | `/Users/jhonwheeler/wheellsverse-kai-exec-integration` |
| **App A** (app.wheellsverse.com) | `feat/kai-exec-appa-integration` | `4a675d7` | `/Users/jhonwheeler/wheellsverse-kai-appa-integration` |
| App B rollback (current prod) | `feature/kai-holding-operations-os` | `914855d` | — |
| App A rollback (current prod) | `production` | `e9988c5` | — |

## Verification (both branches, all green)
- **App B** `82c1a53`: capability 13 files / **173** tests · real `app.main:app` flag **OFF → 0** routes, **ON → 6** · holding preserved (0-line diff) · reasoning-sanitizer 26.
- **App A** `4a675d7`: `/admin/capabilities.json` → **126** caps · nexus module **16** · page contract **7** (loads module, bridge-only, no App B URL, no `/admin/capability` typo) · bridge **27** (capabilities owner-only) · `core.api` imports clean.
- No arbitrary shell · 0 financial exec · 0 restricted runtimes · MONEY_MODE=MOCK.

## OPERATOR DEPLOY ORDER (§22) — exact commands

### A. Deploy App B, flag OFF
```bash
cd /Users/jhonwheeler/wheellsverse-kai-exec-integration        # or the kai-production-linked worktree
git fetch && git checkout feat/kai-exec-appb-integration       # 82c1a53
railway status                                                 # MUST show project=kai-production, service=kai-prod
railway up --service kai-prod --detach
```
### B. Wait for terminal **SUCCESS** (replicas healthy, 0 crash loop).
### C. App B flag-OFF smoke (proves the latch):
```bash
BASE=https://kai-prod-production.up.railway.app
curl -s --max-time 15 "$BASE/health"                                            # env=production status=ok
curl -s -o /dev/null -w "%{http_code}\n" "$BASE/admin/capabilities"             # 404 = routes NOT mounted (flag off) ✓
```
### D. Deploy App A (git-connected; merge integration → production → push):
```bash
cd /Users/jhonwheeler/conductor/repos/wheellsverse-bots        # a worktree tracking production
git fetch && git checkout production                           # e9988c5
git merge --no-ff feat/kai-exec-appa-integration -m "deploy(app-a): capability execution UI V1"
git push origin production                                     # triggers App A (grateful-flexibility) auto-deploy
```
### E. Wait for App A deploy **SUCCESS**.
### F. Browser-smoke App A **before enabling execution**:
Open `https://app.wheellsverse.com/admin/capabilities` — the Capabilities view renders (126 caps), the
banner reads **EXECUTION DISABLED (catalog browsing only)**, inspector shows no TEST button. No console errors.
### G. Enable execution on App B:
```bash
railway variables --set KAI_CAPABILITY_EXECUTION_ENABLED=true --service kai-prod
railway up --service kai-prod --detach     # H. redeploy if the var needs a restart; wait for SUCCESS
```
### I. First real production execution — yt-dlp metadata (§24), owner-authorized:
```bash
curl -s -X POST "$BASE/admin/capabilities/yt-dlp/invoke" \
  -H 'Content-Type: application/json' -H "Cookie: wv_session=<owner session>" \
  -d '{"operation":"metadata","input":{"url":"https://archive.org/details/BigBuckBunny_124"}}'
# expect: status OK · evidence.title="Big Buck Bunny" · provenance REAL · NO download
curl -s -X POST "$BASE/admin/capabilities/yt-dlp/invoke" -H 'Content-Type: application/json' \
  -H "Cookie: wv_session=<owner session>" -d '{"operation":"download","input":{"url":"https://archive.org/details/BigBuckBunny_124"}}'
# expect: 403 OPERATION_NOT_ENABLED
```
### J. KAI command routing (§25): "KAI, inspect the metadata for this approved public media URL." → Brain selects yt-dlp → same service executes → Nexus reflects it.
### K. Live browser certification (§26) — from `https://app.wheellsverse.com/admin/capabilities`:
open yt-dlp inspector → press **TEST** → RUNNING→COMPLETED → history row appears → halo pulses; then
`codebase-memory-mcp` shows EXTERNAL_BLOCKED, Empire shows DISABLED_RESTRICTED_LAB_ONLY. Desktop
(3440/1920/1440) + mobile (390×844), no console errors. Capture the 8 screenshots (§26).

## ROLLBACK (§41)
1. `railway variables --set KAI_CAPABILITY_EXECUTION_ENABLED=false --service kai-prod` (instant latch off)
2. App B code: `git checkout feature/kai-holding-operations-os` (914855d) + `railway up --service kai-prod`
3. App A: `git checkout production && git reset --hard e9988c5 && git push --force-with-lease` (or revert the merge)

## Guardrails (unchanged by this deploy)
MONEY_MODE=MOCK · financial exec OFF · Empire/Strix/reverse-skill-active/SecLists/Payloads catalog-only ·
arbitrary shell ABSENT · codebase-memory-mcp EXTERNAL_BLOCKED in prod · MarkItDown fixture-only (USER_FILE_INPUT_PENDING).
