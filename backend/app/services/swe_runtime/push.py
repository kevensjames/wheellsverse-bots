"""Git push for the autonomous SWE agent — Gate 2's side effect.

Applies the approved patch on a FRESH CLONE (never the operator's live checkout)
and pushes it to a NON-DEFAULT review branch `kai/swe/<task_id>` using a
repo-scoped, least-privilege credential. Hard guards (see
plans/PLAN-kai-autonomous-swe-agent.md §6):

  - branch-only: the destination is always `kai/swe/<id>`; a protected branch is
    refused; `--force` is never emitted (a non-fast-forward push just fails).
  - CI-poisoning block: after apply, git's OWN affected-path list is checked and
    the push is refused if it touches `.github/workflows/**`, `.gitlab-ci.yml`,
    `.gitlab/**`, or `.git/hooks/**` (a cheap raw-text pre-check rejects the
    obvious case earlier). Using git's canonical paths defeats C-quoted-name and
    rename/copy bypasses that raw-text parsing misses.
  - no ambient credential: the push runs with empty HOME + GIT_CONFIG_GLOBAL/
    SYSTEM and GIT_TERMINAL_PROMPT=0, so no `~/.git-credentials`,
    `credential.helper`, or ambient token is ever used. A remote host requires an
    explicit `KAI_SWE_PUSH_TOKEN`; ssh/http remotes are refused. The token is
    supplied ONLY through an in-env GIT_ASKPASS helper — never on disk (the helper
    script reads it from the subprocess env), never in argv, never in git config.
  - fail-closed audit: the push aborts if its audit line cannot be durably
    (fsync'd) persisted first — overriding record_action's usual fail-soft.

All git calls use argv lists (never a shell). Nothing here runs on the prod
daemon (the router is mounted only on a non-prod runner).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

from app.services.swe_runtime.policy import PolicyDenied

logger = logging.getLogger(__name__)


class PushError(Exception):
    """A git operation failed (clone/apply/commit/push). Maps to HTTP 503."""


_REF_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_CI_PREFIXES = (".github/workflows/", ".gitlab/", ".git/hooks/")
_CI_EXACT = frozenset({".gitlab-ci.yml"})


def _protected_branches() -> frozenset[str]:
    raw = (os.environ.get("KAI_SWE_PROTECTED_BRANCHES") or "main,istanbul,master").strip()
    return frozenset(b.strip() for b in raw.split(",") if b.strip())


def resolve_push_credential() -> str | None:
    """The single repo-scoped push token (fine-grained, contents:write, no
    workflows). None → the caller refuses to push (no ambient fallback)."""
    return (os.environ.get("KAI_SWE_PUSH_TOKEN") or "").strip() or None


def review_branch_for(task_id: str) -> str:
    """`kai/swe/<task_id>` after validating task_id is a safe ref component (no
    traversal, no leading '-'/'.', git-ref-legal)."""
    if not _REF_COMPONENT_RE.match(task_id) or ".." in task_id:
        raise PolicyDenied(f"unsafe task_id for a git ref: {task_id!r}")
    return f"kai/swe/{task_id}"


def _is_ci_path(p: str) -> bool:
    return p in _CI_EXACT or any(p.startswith(x) for x in _CI_PREFIXES)


def _patch_touches_ci(patch: str) -> bool:
    """CHEAP pre-apply reject for the obvious ASCII case. NOT authoritative — git
    can C-quote non-ASCII header paths and express moves as renames (no +++/---
    line), both of which slip past raw-text parsing. The real guard is
    _staged_ci_paths() on git's own post-apply path model."""
    for line in patch.splitlines():
        if not (line.startswith("+++ ") or line.startswith("--- ")):
            continue
        p = line[4:].strip()
        for pre in ("a/", "b/"):
            if p.startswith(pre):
                p = p[len(pre):]
                break
        if p == "/dev/null":
            continue
        if _is_ci_path(p):
            return True
    return False


def _staged_ci_paths(work: str) -> list[str]:
    """AUTHORITATIVE CI guard: after `git add -A`, ask git for the affected paths
    (canonical — handles C-quoted names, renames, and copies) and return any CI/
    hook paths. core.quotepath=false so names come back literal, not octal-escaped."""
    r = _git(["-C", work, "-c", "core.quotepath=false",
              "diff", "--cached", "--name-only", "--find-renames"])
    return [p.strip() for p in r.stdout.splitlines() if p.strip() and _is_ci_path(p.strip())]


def _is_local_remote(url: str) -> bool:
    return url.startswith(("/", "file://", ".")) or os.path.isdir(url)


def _https_push_url(origin: str, username: str = "x-access-token") -> str:
    """Normalize a remote to an https URL carrying only a username (the token is
    supplied via GIT_ASKPASS). ssh/http are refused so no ambient key is used."""
    if origin.startswith("git@"):                     # git@host:owner/repo.git
        host, _, path = origin[4:].partition(":")
        return f"https://{username}@{host}/{path}"
    if origin.startswith("https://"):
        rest = origin[len("https://"):]
        if "@" in rest.split("/", 1)[0]:              # strip any embedded userinfo
            rest = rest.split("@", 1)[1]
        return f"https://{username}@{rest}"
    if origin.startswith("http://"):
        raise PolicyDenied("refusing to push over http (use https)")
    raise PolicyDenied(f"unsupported remote scheme (use https or a local path): {origin!r}")


def _redact_remote(url: str) -> str:
    """Strip any userinfo from a URL for logging."""
    return re.sub(r"//[^@/]+@", "//", url)


def _git(args: list[str], *, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout, env=env)


def _run_or_raise(args: list[str], *, env: dict | None = None, timeout: int = 120) -> str:
    r = _git(args, env=env, timeout=timeout)
    if r.returncode != 0:
        raise PushError(f"git {args[0]} failed: {_redact_remote(r.stderr)[:400]}")
    return r.stdout.strip()


def _push_env(token: str | None, home: str) -> dict:
    """Env that strips every ambient credential source and (if a token is given)
    supplies it only via an in-env GIT_ASKPASS helper."""
    env = dict(os.environ)
    env["HOME"] = home                                       # no ~/.gitconfig, ~/.git-credentials
    env["GIT_CONFIG_GLOBAL"] = os.path.join(home, "no-global-gitconfig")   # nonexistent → ignored
    env["GIT_CONFIG_SYSTEM"] = os.path.join(home, "no-system-gitconfig")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop("SSH_ASKPASS", None)
    env.pop("GIT_ASKPASS", None)
    if token:
        helper = os.path.join(home, "askpass.sh")
        with open(helper, "w") as f:                         # the token is NOT in this file
            f.write('#!/bin/sh\nprintf "%s" "$KAI_SWE_ASKPASS_TOKEN"\n')
        os.chmod(helper, 0o700)
        env["GIT_ASKPASS"] = helper
        env["KAI_SWE_ASKPASS_TOKEN"] = token                 # only in the subprocess env
    return env


def _write_push_audit_or_raise(*, task_id: str, actor: str, branch: str, remote: str) -> None:
    """Fail-CLOSED audit: durably record the push attempt BEFORE pushing. Unlike
    record_action (fail-soft), a write failure here aborts the push."""
    from app.services.governance.audit_log import AUDIT_LOG_PATH
    rec = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "swe_push_attempt", "scope": "swepush.execute",
        "actor": actor, "destructive": True, "approved": True,
        "task_id": task_id, "review_branch": branch, "remote": remote,
    }
    try:
        with open(AUDIT_LOG_PATH, "a") as fp:
            fp.write(json.dumps(rec) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
    except Exception as e:
        raise PushError(f"fail-closed: could not persist push audit ({e}); refusing to push")


def apply_and_push(*, source_dir: str, task_id: str, patch: str, actor: str,
                   message: str | None = None) -> dict:
    """Fresh-clone → branch → git apply → commit → push to kai/swe/<id>. Returns
    {review_branch, remote, commit}. Raises PolicyDenied (guard) / PushError (git)."""
    if not patch or not patch.strip():
        raise PolicyDenied("empty patch")
    branch = review_branch_for(task_id)                      # validates task_id
    if branch in _protected_branches() or task_id in _protected_branches():
        raise PolicyDenied(f"refusing to push to a protected branch ({branch})")
    if _patch_touches_ci(patch):
        raise PolicyDenied("patch touches CI/hook paths (.github/workflows, .gitlab-ci.yml, .gitlab/, .git/hooks)")

    if not os.path.isdir(os.path.join(source_dir, ".git")):
        raise PolicyDenied("source_dir is not a git repository")
    if _git(["-C", source_dir, "status", "--porcelain"]).stdout.strip():
        raise PolicyDenied("source_dir has uncommitted changes; commit or stash before push")

    origin = _run_or_raise(["-C", source_dir, "remote", "get-url", "origin"])
    base_ref = _run_or_raise(["-C", source_dir, "rev-parse", "HEAD"])

    local = _is_local_remote(origin)
    token = None
    if not local:
        token = resolve_push_credential()
        if not token:
            raise PolicyDenied("no push credential (set KAI_SWE_PUSH_TOKEN); refusing ambient fallback")
    push_url = origin if local else _https_push_url(origin)

    work = tempfile.mkdtemp(prefix="kai-swe-push-")
    home = tempfile.mkdtemp(prefix="kai-swe-githome-")
    try:
        _run_or_raise(["clone", "--quiet", "--no-hardlinks", source_dir, work])
        _run_or_raise(["-C", work, "checkout", "-q", "-b", branch, base_ref])

        patch_file = os.path.join(home, "change.patch")      # outside the work tree
        with open(patch_file, "w") as f:
            f.write(patch if patch.endswith("\n") else patch + "\n")
        ap = _git(["-C", work, "apply", "--whitespace=nowarn", patch_file])
        if ap.returncode != 0:
            raise PushError(f"git apply failed: {ap.stderr[:400]}")

        _run_or_raise(["-C", work, "add", "-A"])
        # AUTHORITATIVE CI-poisoning guard — on git's OWN affected-paths, after
        # apply, before commit/push. Defeats the C-quoted-name and rename/copy
        # bypasses that the raw-text pre-check cannot see.
        ci_hits = _staged_ci_paths(work)
        if ci_hits:
            raise PolicyDenied("patch affects CI/hook paths: " + ", ".join(sorted(ci_hits)))

        _run_or_raise(["-C", work,
                       "-c", "user.name=KAI SWE Agent",
                       "-c", "user.email=kai-swe@wheellsverse.local",
                       "-c", "commit.gpgsign=false",
                       "commit", "-m", message or f"KAI SWE agent: {task_id}"])
        commit = _run_or_raise(["-C", work, "rev-parse", "HEAD"])

        # Fail-closed audit immediately before the remote write (past every guard).
        _write_push_audit_or_raise(task_id=task_id, actor=actor, branch=branch,
                                   remote=_redact_remote(origin))

        env = _push_env(token, home)
        pr = _git(["-C", work, "push", push_url, f"{branch}:{branch}"], env=env)
        if pr.returncode != 0:
            raise PushError(f"git push failed: {_redact_remote(pr.stderr)[:400]}")

        return {"review_branch": branch, "remote": _redact_remote(origin), "commit": commit}
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
