"""REPO_INSPECT runtime (Part A, §1-15) — a strictly READ-ONLY repository inspection capability.

REPO_INSPECT is a LOGICAL holding task, not `github.read` (§1). A company's authoritative repo is
resolved from holding metadata to a typed RepositoryIdentity, then to a certified read-only provider.
If no certified provider backs that repo, the result is BLOCKED_CAPABILITY — never a silent mirror.

The only genuinely-certified provider today is the in-process read-only LocalGitProvider over this
monorepo (no credentials/network). GitHub/Gitea are declared providers with no certified backend yet.

Hard guarantees: no write operation exists in any provider (§4); sensitive-file CONTENT is denied
UPSTREAM before any read (§5); path/branch traversal is rejected; reads are size-bounded (§7) and
redacted (§6, reusing the hardened redactor); every result carries provenance (§9). Pure/injectable —
providers can be faked for deterministic tests, and the LocalGitProvider is exercised live for cert.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, asdict
from enum import Enum

from app.services.holding.task_resolver import redact, is_forbidden_repo_target


class RepoOp(str, Enum):
    REPOSITORY_STATUS = "REPOSITORY_STATUS"
    LATEST_COMMIT = "LATEST_COMMIT"
    BRANCH_METADATA = "BRANCH_METADATA"
    FILE_METADATA = "FILE_METADATA"
    READ_FILE = "READ_FILE"
    LIST_DIRECTORY = "LIST_DIRECTORY"
    ISSUES_READ = "ISSUES_READ"
    PULL_REQUESTS_READ = "PULL_REQUESTS_READ"


# Operations that are read-only metadata (never touch file CONTENT).
_METADATA_OPS = {RepoOp.REPOSITORY_STATUS, RepoOp.LATEST_COMMIT, RepoOp.BRANCH_METADATA,
                 RepoOp.FILE_METADATA, RepoOp.LIST_DIRECTORY}

# §7 size limits (server-enforced).
MAX_BYTES_PER_FILE = 256 * 1024
MAX_DIR_ENTRIES = 500
MAX_FILES_PER_INVOCATION = 20


class RepoDenied(Exception):
    """Raised when a request violates the read-only / sensitive-path / traversal / size policy."""


@dataclass
class RepositoryIdentity:
    repository_id: str
    provider: str                # "local-git" | "github" | "gitea" | ...
    owner: str
    repository: str
    default_branch: str
    company_id: str
    project_id: str = ""
    local_root: str = ""         # only for local-git

    def as_dict(self) -> dict:
        d = asdict(self); d.pop("local_root", None); return d   # never leak the absolute FS root


# ── path safety (§14 traversal) ──────────────────────────────────────────────────────────────────
def _safe_join(root: str, rel: str) -> str:
    """Resolve rel within root, rejecting absolute paths, .. traversal, and symlink escapes."""
    if not isinstance(rel, str) or rel == "" or rel.startswith("/") or rel.startswith("~"):
        raise RepoDenied("path must be a relative in-repo path")
    if ".." in rel.replace("\\", "/").split("/"):
        raise RepoDenied("path traversal rejected")
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, rel))
    if target != root_real and not target.startswith(root_real + os.sep):
        raise RepoDenied("path escapes the repository root")
    return target


# ── providers ─────────────────────────────────────────────────────────────────────────────────────
class LocalGitProvider:
    """CERTIFIED read-only provider over a local git working tree. Every git command is a FIXED,
    server-owned read-only arg list (never a shell string, never task free-text) — subprocess without
    shell. No write command exists here."""
    name = "local-git"

    def __init__(self, root: str):
        self.root = os.path.realpath(root)

    def _git(self, *args: str) -> str:
        # fixed read-only git subcommands only; list args, shell=False, bounded timeout
        out = subprocess.run(["git", "-C", self.root, *args], capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            raise RepoDenied(f"git read failed: {(out.stderr or '').strip()[:80]}")
        return out.stdout

    def health(self) -> dict:
        try:
            self._git("rev-parse", "--is-inside-work-tree")
            return {"state": "READY"}
        except Exception as e:
            return {"state": "UNAVAILABLE", "reason": str(e)[:80]}

    def repository_status(self) -> dict:
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        head = self._git("rev-parse", "HEAD").strip()
        dirty = bool(self._git("status", "--porcelain").strip())
        return {"branch": branch, "commit_sha": head, "dirty": dirty}

    def latest_commit(self) -> dict:
        raw = self._git("log", "-1", "--format=%H%n%an%n%aI%n%s")
        h, an, ad, *subj = raw.splitlines()
        return {"commit_sha": h, "author": an, "authored_at": ad, "subject": (subj[0] if subj else "")}

    def branch_metadata(self) -> dict:
        cur = self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        branches = [b.strip().lstrip("* ").strip() for b in self._git("branch", "--list").splitlines()][:50]
        return {"current_branch": cur, "branches": branches}

    def file_metadata(self, rel: str) -> dict:
        target = _safe_join(self.root, rel)
        exists = os.path.exists(target)
        size = os.path.getsize(target) if (exists and os.path.isfile(target)) else None
        # §5: metadata MAY indicate a sensitive file exists, but flags it — content stays denied.
        return {"path": rel, "exists": exists, "size": size, "is_sensitive": is_forbidden_repo_target(rel),
                "is_dir": exists and os.path.isdir(target)}

    def read_file(self, rel: str) -> dict:
        # §5: deny CONTENT of sensitive files UPSTREAM — do not read the bytes at all.
        if is_forbidden_repo_target(rel):
            raise RepoDenied("sensitive file content denied")
        target = _safe_join(self.root, rel)
        if not os.path.isfile(target):
            raise RepoDenied("not a readable file")
        with open(target, "rb") as f:
            raw = f.read(MAX_BYTES_PER_FILE + 1)
        truncated = len(raw) > MAX_BYTES_PER_FILE
        raw = raw[:MAX_BYTES_PER_FILE]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"path": rel, "binary": True, "content": None, "truncated": truncated}
        # §6: redact content before it becomes evidence (second net after upstream denial)
        return {"path": rel, "binary": False, "content": redact(text), "truncated": truncated,
                "bytes": len(raw)}

    def list_directory(self, rel: str) -> dict:
        target = _safe_join(self.root, rel or ".")
        if not os.path.isdir(target):
            raise RepoDenied("not a directory")
        entries = sorted(os.listdir(target))[:MAX_DIR_ENTRIES]
        return {"path": rel or ".", "entries": entries, "truncated": len(os.listdir(target)) > MAX_DIR_ENTRIES}


# ── repository resolver (§1) — company → typed identity → provider ────────────────────────────────
def _monorepo_root() -> str:
    # backend/app/services/holding/repo_inspect.py → repo root is parents[4]
    from pathlib import Path
    return str(Path(__file__).resolve().parents[4])


def resolve_repository(company_id: str, *, entities=None, monorepo_root: str | None = None) -> RepositoryIdentity | None:
    """Resolve a company to its authoritative RepositoryIdentity from holding metadata (§1). Companies
    whose repo is THIS monorepo get the certified local-git provider; a distinct external repo gets a
    declared provider (github/gitea) with no certified backend yet. None if the company is unknown."""
    if entities is None:
        from app.services.holding import registry as reg
        entities = reg.all_entities()
    ent = next((e for e in entities if getattr(e, "entity_id", None) == company_id), None)
    if ent is None:
        return None
    repo_str = (getattr(ent, "repository", None) or "").strip()
    if not repo_str:
        return None
    root = monorepo_root or _monorepo_root()
    if "wheellsverse-bots" in repo_str:                       # the local monorepo → certified provider
        return RepositoryIdentity(repository_id=f"local:{company_id}", provider="local-git",
                                  owner="kevensjames", repository="wheellsverse-bots",
                                  default_branch="main", company_id=company_id, local_root=root)
    # a distinct external repo — declared provider, no certified read backend yet (fail closed at exec)
    prov = "gitea" if "gitea" in repo_str.lower() else "github"
    return RepositoryIdentity(repository_id=f"{prov}:{company_id}", provider=prov, owner="wheellsverse",
                              repository=repo_str.split()[0], default_branch="main", company_id=company_id)


# ── the executor provider (routed to by build_holding_executor for capability "holding.repo") ──────
def make_repo_provider(*, providers: dict | None = None, entities=None, monorepo_root: str | None = None):
    """Return provider(args) -> evidence dict for the composite executor. `providers` maps a provider
    name → a live provider object; only certified ones are present (default: local-git). Fails closed
    (raises) when the company has no certified provider, when the op is unknown/forbidden, or on policy."""
    def _build_local(ident):
        return LocalGitProvider(ident.local_root)
    live = providers or {}

    def provider(args: dict) -> dict:
        company_id = (args or {}).get("company_id", "")
        ident = resolve_repository(company_id, entities=entities, monorepo_root=monorepo_root)
        if ident is None:
            raise RepoDenied("unknown company / no repository")
        impl = live.get(ident.provider)
        if impl is None and ident.provider == "local-git":
            impl = _build_local(ident)                        # certified default
        if impl is None:
            raise RepoDenied(f"no certified read provider for '{ident.provider}'")
        h = impl.health()
        if h.get("state") != "READY":
            raise RepoDenied(f"provider unhealthy: {h.get('reason', '')}")
        op = (args or {}).get("operation", RepoOp.REPOSITORY_STATUS.value)
        try:
            op_enum = RepoOp(op)
        except ValueError:
            raise RepoDenied(f"unknown repo operation '{op}'")
        if op_enum in (RepoOp.ISSUES_READ, RepoOp.PULL_REQUESTS_READ) and ident.provider == "local-git":
            raise RepoDenied("issues/PRs not available from a local git provider")
        # dispatch (all read-only)
        if op_enum == RepoOp.REPOSITORY_STATUS:
            data = impl.repository_status()
        elif op_enum == RepoOp.LATEST_COMMIT:
            data = impl.latest_commit()
        elif op_enum == RepoOp.BRANCH_METADATA:
            data = impl.branch_metadata()
        elif op_enum == RepoOp.FILE_METADATA:
            data = impl.file_metadata(args.get("path", ""))
        elif op_enum == RepoOp.READ_FILE:
            data = impl.read_file(args.get("path", ""))
        elif op_enum == RepoOp.LIST_DIRECTORY:
            data = impl.list_directory(args.get("path", ""))
        else:
            raise RepoDenied(f"operation '{op}' not supported by this provider")
        # §9 provenance + §6 final redaction pass
        evidence = {"provider": ident.provider, "repository_id": ident.repository_id,
                    "repository": ident.repository, "operation": op_enum.value,
                    "company_id": ident.company_id, **data}
        return redact(evidence)

    return provider


if __name__ == "__main__":
    from app.services.holding.test_repo_inspect import run
    run()
