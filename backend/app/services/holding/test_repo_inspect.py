"""Tests for REPO_INSPECT (Part A, §13-14). File-op security tests run on a temp dir (deterministic);
git-metadata ops run LIVE against the real monorepo for certification.
Run: python3 backend/app/services/holding/test_repo_inspect.py"""
import sys
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.repo_inspect import (  # noqa: E402
    LocalGitProvider, RepoDenied, resolve_repository, make_repo_provider, RepoOp,
    MAX_BYTES_PER_FILE)
from app.services.holding.task_resolver import REDACTED  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


# ── temp repo fixture (filesystem only; no git needed for file ops) ────────────────────────────────
_TMP = tempfile.mkdtemp(prefix="repoinspect-")
Path(_TMP, ".env").write_text("SECRET_KEY=sk-proj-abcdefghijklmnop0123456789ABCDEF\n")
Path(_TMP, "server.key").write_text("-----BEGIN PRIVATE KEY-----\nMIIEvz...\n-----END PRIVATE KEY-----\n")
Path(_TMP, "app.py").write_text("TOKEN = 'ghp_0123456789abcdefABCDEF0123456789abcd'\nprint('ok')\n")
Path(_TMP, "big.txt").write_text("x" * (MAX_BYTES_PER_FILE + 500))
Path(_TMP, "bin.dat").write_bytes(bytes(range(256)) * 4)
os.makedirs(Path(_TMP, "sub"), exist_ok=True)
Path(_TMP, "sub", "a.txt").write_text("hello")
_LP = LocalGitProvider(_TMP)


def t_read_normal_file_redacted():
    r = _LP.read_file("app.py")
    assert r["binary"] is False and "ok" in r["content"]
    assert "ghp_0123456789" not in r["content"] and REDACTED in r["content"]   # §6 secret redacted


def t_sensitive_content_denied_upstream():
    """§5: .env and *.key CONTENT denied before any read (not merely redacted after)."""
    for bad in (".env", "server.key"):
        try:
            _LP.read_file(bad); assert False, f"{bad} content should be denied"
        except RepoDenied:
            pass
    # but metadata MAY reveal existence + sensitivity flag
    m = _LP.file_metadata(".env")
    assert m["exists"] and m["is_sensitive"] and "content" not in m


def t_path_traversal_rejected():
    for bad in ("../etc/passwd", "/etc/passwd", "sub/../../x", "~/secrets"):
        try:
            _LP.read_file(bad); assert False, f"{bad} should be rejected"
        except RepoDenied:
            pass


def t_oversized_truncated():
    r = _LP.read_file("big.txt")
    assert r["truncated"] is True and r["bytes"] == MAX_BYTES_PER_FILE


def t_binary_not_dumped():
    r = _LP.read_file("bin.dat")
    assert r["binary"] is True and r["content"] is None


def t_list_directory_bounded():
    r = _LP.list_directory(".")
    assert ".env" in r["entries"] and "app.py" in r["entries"]
    try:
        _LP.list_directory("../.."); assert False
    except RepoDenied:
        pass


# ── resolver (§1) — inject fake entities ──────────────────────────────────────────────────────────
def _ents():
    return [SimpleNamespace(entity_id="kai", repository="wheellsverse-bots (core/api.py)"),
            SimpleNamespace(entity_id="sol", repository="wheellsverse-sol (standalone) + wheellsverse-bots"),
            SimpleNamespace(entity_id="nurtelle", repository="kevensjames/chenara (private)"),
            SimpleNamespace(entity_id="ghost", repository="")]


def t_resolve_local_vs_external():
    kai = resolve_repository("kai", entities=_ents(), monorepo_root="/repo")
    assert kai.provider == "local-git" and kai.local_root == "/repo"
    nur = resolve_repository("nurtelle", entities=_ents())
    assert nur.provider == "github" and nur.local_root == ""     # external → not certified
    assert resolve_repository("ghost", entities=_ents()) is None  # no repo
    assert resolve_repository("nope", entities=_ents()) is None   # unknown company
    assert "local_root" not in kai.as_dict()                     # never leak the FS root


# ── factory policy (§14) ──────────────────────────────────────────────────────────────────────────
def _factory(providers=None):
    return make_repo_provider(providers=providers, entities=_ents(), monorepo_root=_TMP)


def t_factory_unknown_and_external_fail_closed():
    prov = _factory()
    for args in ({"company_id": "nope"}, {"company_id": "ghost"}):
        try:
            prov(args); assert False
        except RepoDenied:
            pass
    try:
        prov({"company_id": "nurtelle"}); assert False, "external provider has no certified backend"
    except RepoDenied:
        pass


def t_factory_forged_op_and_sensitive_denied():
    # inject a fake local-git impl so file ops work without a real git repo
    fake = _FakeProvider()
    prov = _factory(providers={"local-git": fake})
    try:
        prov({"company_id": "kai", "operation": "DELETE_BRANCH"}); assert False
    except RepoDenied:
        pass
    try:
        prov({"company_id": "kai", "operation": "READ_FILE", "path": ".env"}); assert False
    except RepoDenied:
        pass
    # a legit metadata op works and carries provenance
    ev = prov({"company_id": "kai", "operation": "REPOSITORY_STATUS"})
    assert ev["provider"] == "local-git" and ev["operation"] == "REPOSITORY_STATUS" and ev["commit_sha"] == "deadbeef"


class _FakeProvider:
    name = "local-git"
    def health(self): return {"state": "READY"}
    def repository_status(self): return {"branch": "main", "commit_sha": "deadbeef", "dirty": False}
    def read_file(self, rel):
        from app.services.holding.repo_inspect import is_forbidden_repo_target
        if is_forbidden_repo_target(rel):
            raise RepoDenied("sensitive")
        return {"path": rel, "content": "x", "binary": False, "truncated": False}


def t_factory_unhealthy_provider_blocks():
    class Down:
        name = "local-git"
        def health(self): return {"state": "UNAVAILABLE", "reason": "no git"}
    try:
        _factory(providers={"local-git": Down()})({"company_id": "kai"}); assert False
    except RepoDenied:
        pass


# ── LIVE certification smoke: real git metadata over the actual monorepo ───────────────────────────
def t_live_git_metadata_certifies():
    root = str(Path(__file__).resolve().parents[4])   # monorepo root
    lp = LocalGitProvider(root)
    assert lp.health().get("state") == "READY", "monorepo must be a git work tree"
    st = lp.repository_status()
    assert len(st["commit_sha"]) == 40 and st["branch"]
    lc = lp.latest_commit()
    assert len(lc["commit_sha"]) == 40 and lc["subject"]
    bm = lp.branch_metadata()
    assert bm["current_branch"] and isinstance(bm["branches"], list)


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
