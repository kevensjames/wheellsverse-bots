"""A2 coding worker leaf — the EXECUTION RESOURCE (runs on the colima host where .git lives).

Given a governed A2 coding job (dispatched by deployed KAI via worker_jobs), this builds the certified
A2Framework ON THE HOST and runs the WHOLE prepare(): real isolated worktree → the coding worker makes a
bounded change → the framework re-derives the AUTHORITATIVE git diff (never the worker's self-report) →
shared authority/dependency/binary/oversized gates → independent certified-suite test → independent review
→ READY_FOR_REVIEW. It NEVER merges, pushes, or deploys. It returns the A2Prepared evidence; deployed KAI
re-verifies it (a2_dispatch.verify_a2_evidence) before setting the authoritative decision.

The coding worker itself is a thin, swappable seam: set KAI_CODING_CLI to run a real headless coding tool
(claude/codex/aider) in the worktree; unset, a deterministic in-repo stand-in applies a bounded fix so the
whole governed chain is certifiable before a host CLI is wired. Either way the framework re-checks the
result — the worker is never trusted.
"""
import os
import subprocess
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO_DEFAULT, "backend"))


def _deterministic_worker(task, wt):
    """Stand-in coding worker: a bounded, non-authority fix to the disposable fixture. Returns a
    WorkerResult whose self-reported fields are IGNORED by the framework (it re-derives the real diff)."""
    from app.services.capability.coding import WorkerResult
    target = os.path.join(wt.worktree, "ops/a2-cert-fixture/target.py")
    with open(target, "a") as f:
        f.write("\n\ndef mul(a, b):\n    return a * b\n")
    return WorkerResult(task="fix", worker="coding-deterministic", starting_sha=wt.starting_sha,
                        files_changed=["<self-report ignored>"], diff_summary="added mul()",
                        artifacts=["draft-pr"])


# The CLI subprocess gets a SCRUBBED env — ONLY an explicit allowlist (goal + cwd + the model-API key the
# tool needs), never the runner's full environment. This is the §35 credential-isolation prerequisite for
# enabling KAI_CODING_CLI: without it a wired CLI would inherit SESSION_SIGNING_SECRET / DATABASE_URL /
# SECRET_KEY under `railway run` and could exfil them — a network side-effect invisible to every diff gate
# and to owner-review-before-merge. The allowlist is operator-controlled via KAI_CODING_CLI_ENV_ALLOW.
_ENV_ALLOW_DEFAULT = "PATH,HOME,LANG,LC_ALL,TERM,ANTHROPIC_API_KEY,OPENAI_API_KEY"


def _scrubbed_env() -> dict:
    allow = {k.strip() for k in os.environ.get("KAI_CODING_CLI_ENV_ALLOW", _ENV_ALLOW_DEFAULT).split(",") if k.strip()}
    return {k: v for k, v in os.environ.items() if k in allow}


def _dirty(worktree: str) -> bool:
    r = subprocess.run(["git", "-C", worktree, "status", "--porcelain"], capture_output=True, text=True, timeout=15)
    return bool((r.stdout or "").strip())


def _cli_worker(clis: list):
    """Real coding worker with an ORDERED fallback (e.g. claude primary, codex backup). Each CLI runs
    headless in the worktree with a SCRUBBED env (no runner secrets); the FIRST that actually produces a
    change wins. Never pushes; the framework derives the authoritative diff and the worker is never trusted.
    A CLI that errors or makes no change (e.g. an auth failure under the scrub) simply yields to the next."""
    def w(task, wt):
        from app.services.capability.coding import WorkerResult
        goal = str(task.get("goal", "") if isinstance(task, dict) else getattr(task, "goal", ""))[:500]
        warnings, used = [], ""
        for cli in [c for c in clis if c.strip()]:
            name = cli.split()[0]
            try:
                p = subprocess.run([*cli.split(), goal], cwd=wt.worktree, env=_scrubbed_env(),
                                   capture_output=True, text=True, timeout=600)
                if p.returncode != 0:
                    warnings.append(f"{name} exit {p.returncode}: {(p.stderr or p.stdout or '')[:80]}")
            except Exception as e:
                warnings.append(f"{name} error: {str(e)[:80]}")
            if _dirty(wt.worktree):                        # this CLI made a change → use it
                used = name
                break
        return WorkerResult(task="fix", worker=used or (clis[0].split()[0] if clis else "cli"),
                            starting_sha=wt.starting_sha, warnings=warnings)
    return w


def run_coding_task(task: dict, *, repo_dir: str | None = None) -> dict:
    """Execute a governed A2 coding job and return evidence. `status`='completed' means the worker ran the
    governed flow (even a governed OWNER_REQUIRED/BLOCKED is a completed job); 'error' means the runtime
    itself failed. The A2 verdict is in `state`."""
    repo_dir = repo_dir or REPO_DEFAULT
    from app.services.holding.a2_wiring import build_a2_framework, make_worktree_test_fn, remove_worktree
    from app.services.holding.task_resolver import resolve_test_command
    clis = [c for c in (os.environ.get("KAI_CODING_CLI", ""), os.environ.get("KAI_CODING_CLI_BACKUP", "")) if c.strip()]
    worker_fn = _cli_worker(clis) if clis else _deterministic_worker
    suite_cmd = resolve_test_command(str(task.get("suite_id", "")))     # None → default self-model suite
    test_fn = make_worktree_test_fn(suite_cmd) if suite_cmd else make_worktree_test_fn()
    fw = build_a2_framework(repo_dir=repo_dir, worker_fn=worker_fn, test_fn=test_fn)
    mid = str(task.get("task_id", "a2"))
    try:
        prepared = fw.prepare(SimpleNamespace(**task))
        out = prepared.as_dict()
        out["status"] = "completed"
        out["worker"] = "coding-cli" if clis else "coding-deterministic"
        return out
    except Exception as e:
        return {"status": "error", "state": "BLOCKED", "error": str(e)[:200], "merged": False, "deployed": False}
    finally:
        remove_worktree(repo_dir, f"{task.get('base_dir', '/tmp/kai-a2').rstrip('/')}/{mid}-a2", f"kai/{mid}/a2")


if __name__ == "__main__":   # smoke: python3 ops/coding-worker/submit.py
    import json
    sha = subprocess.run(["git", "-C", REPO_DEFAULT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(json.dumps(run_coding_task({"a2_action_type": "EDIT_CODE_IN_WORKTREE", "capability": "coding",
          "company_id": "wheellsverse", "environment": "staging", "task_id": "smoke", "base_sha": sha,
          "base_dir": "/tmp/kai-a2", "suite_id": "holding_self_model", "goal": "add mul()"}), default=str)[:400])
