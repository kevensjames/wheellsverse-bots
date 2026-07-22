"""Walker: deny-by-default allowlist + realpath symlink jail + exclusions."""
import os

from app.services.code_intel.config import CodeIntelPolicy
from app.services.code_intel.walker import iter_files


def _policy(roots, **kw):
    return CodeIntelPolicy(allowlisted_roots=tuple(roots), **kw)


def _names(policy, roots):
    return {wf.rel_path for wf in iter_files(policy, roots)}


def test_indexes_files_under_allowlisted_root(tmp_path):
    (tmp_path / "a.py").write_text("print('hi')\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.js").write_text("console.log(1)\n")
    got = _names(_policy([str(tmp_path)]), [str(tmp_path)])
    assert "a.py" in got and os.path.join("sub", "b.js") in got


def test_deny_by_default_when_no_allowlist(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    # No allowlisted roots => nothing is indexable even if requested.
    assert _names(_policy([]), [str(tmp_path)]) == set()


def test_requested_root_outside_allowlist_is_skipped(tmp_path):
    allowed = tmp_path / "allowed"; allowed.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "secret.py").write_text("x=1\n")
    # Allowlist only 'allowed', but request 'outside' -> skipped entirely.
    assert _names(_policy([str(allowed)]), [str(outside)]) == set()


def test_symlink_escaping_root_is_not_indexed(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    (root / "real.py").write_text("x=1\n")
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "target.txt").write_text("SECRET\n")
    link = root / "escape.txt"
    try:
        os.symlink(outside / "target.txt", link)
    except (OSError, NotImplementedError):
        return  # platform without symlink support
    got = _names(_policy([str(root)]), [str(root)])
    assert "real.py" in got
    assert "escape.txt" not in got  # symlink target escaped the root -> jailed out


def test_excluded_dirs_and_files_are_skipped(tmp_path):
    (tmp_path / "keep.py").write_text("x=1\n")
    nm = tmp_path / "node_modules"; nm.mkdir()
    (nm / "dep.js").write_text("y=2\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / ".git-credentials").write_text("https://u:p@github.com\n")  # dotfile
    (tmp_path / "cert.pem").write_text("-----BEGIN CERTIFICATE-----\n")
    got = _names(_policy([str(tmp_path)]), [str(tmp_path)])
    assert got == {"keep.py"}


def test_oversize_and_binary_skipped(tmp_path):
    (tmp_path / "ok.py").write_text("x=1\n")
    (tmp_path / "big.py").write_text("#" * 2_000_000)      # > 1MB default cap
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02data")  # null byte -> binary
    got = _names(_policy([str(tmp_path)]), [str(tmp_path)])
    assert got == {"ok.py"}
