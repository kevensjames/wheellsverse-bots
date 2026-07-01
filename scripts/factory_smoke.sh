#!/usr/bin/env bash
# KAI Startup Factory — F2d operator-gated REAL smoke.
#
# Runs ONE real engineering cycle with the REAL claude runner + REAL gh against a
# throwaway GitHub repo you own. Costs real Claude $ (~$1-2) and opens a real PR.
# NOTHING here is armed for autonomous runs — it invokes the opt-in `--real` path once.
#
# Usage:
#   scripts/factory_smoke.sh <github-repo-url> [slug]
# Example:
#   scripts/factory_smoke.sh git@github.com:kevensjames/factory-smoke.git smoke
#
# Prereqs (the script checks them): claude CLI logged in, gh authed, gitleaks, python.
# The repo should be EMPTY or trivial and DISPOSABLE. The script seeds it with a
# passing test so the daemon-verified build gate can go green, then asks the real
# agent to add a tiny function.
set -euo pipefail

REPO_URL="${1:?usage: factory_smoke.sh <github-repo-url> [slug]}"
SLUG="${2:-smoke}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE_DATA="$(mktemp -d -t factory-smoke-XXXX)"
export FACTORY_DATA_PATH="$SMOKE_DATA"

echo "== F2d REAL smoke =="
echo "repo:  $REPO_URL"
echo "slug:  $SLUG"
echo "data:  $SMOKE_DATA  (throwaway; deleted at the end)"
echo

echo "-- preflight --"
command -v claude   >/dev/null || { echo "FAIL: claude CLI not on PATH"; exit 1; }
command -v gh       >/dev/null || { echo "FAIL: gh not on PATH"; exit 1; }
command -v gitleaks >/dev/null || echo "WARN: gitleaks missing — security gate will FAIL-CLOSED (block the PR)"
gh auth status >/dev/null 2>&1 || { echo "FAIL: gh not authenticated (run: gh auth login)"; exit 1; }
echo "claude:   $(claude --version 2>/dev/null | head -1)"
echo "gh:       $(gh --version 2>/dev/null | head -1)"
echo "ok."
echo

read -r -p "This will spend real Claude \$ and open a real PR on $REPO_URL. Type 'smoke' to proceed: " CONFIRM
[ "$CONFIRM" = "smoke" ] || { echo "aborted."; rm -rf "$SMOKE_DATA"; exit 1; }

cd "$ROOT"

echo "-- seed the throwaway repo with a passing test (so the build gate can go green) --"
WORK="$(mktemp -d -t factory-smoke-clone-XXXX)"
git clone "$REPO_URL" "$WORK"
cat > "$WORK/test_smoke.py" <<'PY'
def test_placeholder():
    assert True
PY
git -C "$WORK" -c user.email=factory@kai.local -c user.name="KAI Factory" add -A
git -C "$WORK" -c user.email=factory@kai.local -c user.name="KAI Factory" commit -m "smoke: seed passing test" || echo "(nothing to seed — repo already has it)"
git -C "$WORK" push origin HEAD 2>/dev/null || git -C "$WORK" push origin HEAD:main
rm -rf "$WORK"

echo "-- register the project + seed one trivial task --"
python - "$SLUG" "$REPO_URL" <<'PY'
import sys
from factory.project import upsert_project, Project
from factory.state import save_backlog
slug, repo_url = sys.argv[1], sys.argv[2]
upsert_project(Project(slug=slug, name=f"{slug} smoke", repo_url=repo_url))
save_backlog(slug, [{
    "id": "t1",
    "title": "Add a health() function returning the string 'ok' in health.py, with a test.",
    "priority": 1, "status": "pending", "depends_on": [], "source": "smoke", "cycle_id": None,
}])
print(f"registered project {slug!r} -> {repo_url} and seeded task t1")
PY

echo
echo "-- RUN ONE REAL CYCLE (real claude + real gh) --"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# cli --real routes to cycle.run_with_worktree -> real ClaudeCliRunner + worktree lifecycle.
python -m factory tick --real "$SLUG" || { echo "cycle raised — see above"; }

echo
echo "-- RESULT --"
echo "Open PRs on the repo (should include factory/$SLUG/t1 if the cycle completed):"
gh pr list --repo "$(gh repo view "$REPO_URL" --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "$REPO_URL")" 2>/dev/null || \
  echo "  (list PRs manually: gh pr list --repo <owner/repo>)"
echo
echo "Cycle record (status / pr_url / cost):"
python - "$SLUG" <<'PY'
import sys, json, pathlib, os
slug = sys.argv[1]
p = pathlib.Path(os.environ["FACTORY_DATA_PATH"]) / slug / "cycles.jsonl"
if p.exists():
    last = p.read_text().strip().splitlines()[-1]
    r = json.loads(last)
    print(f"  status:  {r.get('status')}")
    print(f"  pr_url:  {r.get('pr_url')}")
    print(f"  cost:    ${float(r.get('cost_usd',0)):.4f}")
    print(f"  stages:  {[s.get('verb')+':'+s.get('status') for s in r.get('stages',[])]}")
else:
    print("  (no cycle record written — the run may have errored before the pipeline)")
PY

echo
echo "== NEXT: manual verification =="
echo " 1. Open the PR on GitHub — confirm it contains health.py + a test, on branch factory/$SLUG/t1."
echo " 2. Confirm the daemon-verified gates ran (stages above show security:executed, build:executed)."
echo " 3. Confirm NO push landed on main (git log origin/main should be unchanged apart from the seed)."
echo " 4. R1 denial: see the runbook for the scoped-Bash / DENY_TOOLS live check."
echo
echo "-- cleanup (throwaway data dir removed; PR/branch left for your inspection) --"
echo "   rm -rf '$SMOKE_DATA'   # already ephemeral"
echo "   To close the PR + delete the branch when done:"
echo "     gh pr close factory/$SLUG/t1 --repo <owner/repo> --delete-branch"
rm -rf "$SMOKE_DATA"
echo "done."
