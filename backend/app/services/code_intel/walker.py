"""Repo file walker: deny-by-default allowlist + realpath symlink jail +
exclusions + binary/oversize skip. Pure filesystem reads; never executes code."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Iterator

from app.services.code_intel.config import CodeIntelPolicy


@dataclass(slots=True)
class WalkedFile:
    abs_path: str
    rel_path: str   # relative to the root it was found under
    root: str       # the resolved root
    size: int


def _realpath(p: str) -> str:
    return os.path.realpath(p)


def _within(child_real: str, root_real: str) -> bool:
    return child_real == root_real or child_real.startswith(root_real + os.sep)


def _root_allowed(root_real: str, policy: CodeIntelPolicy) -> bool:
    return any(_within(root_real, _realpath(a)) for a in policy.allowlisted_roots)


def _excluded_file(name: str, policy: CodeIntelPolicy) -> bool:
    # Dotfiles (.git-credentials, .netrc, .dockercfg, .aws*, .npmrc, …) are
    # excluded by default: low value for code search, high secret risk.
    if name.startswith("."):
        return True
    return any(fnmatch.fnmatch(name, g) for g in policy.exclude_file_globs)


def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(4096)
    except OSError:
        return True


def iter_files(policy: CodeIntelPolicy, requested_roots: list[str]) -> Iterator[WalkedFile]:
    """Yield indexable files under each requested root. A requested root that
    does not resolve under an allowlisted root is skipped ENTIRELY — with no
    allowlist configured, nothing is yielded (deny-by-default)."""
    for root in requested_roots:
        root_real = _realpath(root)
        if not os.path.isdir(root_real) or not _root_allowed(root_real, policy):
            continue
        for dirpath, dirnames, filenames in os.walk(root_real, followlinks=False):
            # Prune excluded, dot-, and jail-escaping dirs in place.
            dirnames[:] = [
                d for d in dirnames
                if d not in policy.exclude_dirs
                and not d.startswith(".")
                and _within(_realpath(os.path.join(dirpath, d)), root_real)
            ]
            for name in filenames:
                abs_path = os.path.join(dirpath, name)
                real = _realpath(abs_path)
                if not _within(real, root_real):
                    continue  # symlink jail: real target escaped the root
                if _excluded_file(name, policy):
                    continue
                try:
                    size = os.path.getsize(real)
                except OSError:
                    continue
                if size == 0 or size > policy.max_file_bytes:
                    continue
                if _is_binary(real):
                    continue
                # Yield the RESOLVED path (the one the jail check validated) so
                # the consumer reads exactly what was validated — not the symlink
                # path (closes a validate-X / read-Y TOCTOU). NOTE: a path-based
                # jail cannot detect a HARDLINK inside the root pointing at an
                # inode outside it; allowlisted roots are operator-controlled
                # trusted trees, and secrets.redact is the defense-in-depth net.
                yield WalkedFile(
                    abs_path=real,
                    rel_path=os.path.relpath(real, root_real),
                    root=root_real,
                    size=size,
                )
