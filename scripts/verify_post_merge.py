#!/usr/bin/env python3
"""Post-merge verifier for the GOD KAI 10-PR integration.

READ-ONLY / TEST-ONLY. This script never deploys, pushes, merges, mutates
production, or touches secrets. It only reads git + source and (optionally) runs
the test suite against an explicitly-configured disposable test database.

Run it right after the ten PRs land on istanbul:

    python scripts/verify_post_merge.py                 # structural checks (fast)
    python scripts/verify_post_merge.py --full          # + governance regression
    python scripts/verify_post_merge.py --full --suite  # + entire pytest suite

Exit code 0 iff every check passes. Expected values come from
docs/execution/MERGE_MANIFEST.json — nothing is hard-coded here.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
MANIFEST = ROOT / "docs" / "execution" / "MERGE_MANIFEST.json"

_results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    _results.append((ok, label))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True).stdout.strip()


def _is_ancestor(commit: str, of: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "merge-base",
                           "--is-ancestor", commit, of],
                          capture_output=True).returncode == 0


def verify_git(manifest: dict, ref: str) -> None:
    head = _git("rev-parse", ref)
    check(bool(head), f"git: resolved {ref}", head[:12])
    missing = [n for n, h in manifest["pr_heads"].items() if not _is_ancestor(h, ref)]
    check(not missing, f"git: all 10 PR heads are ancestors of {ref}",
          "missing: " + ",".join(f"#{n}" for n in missing) if missing else "all present")


def verify_migrations(manifest: dict) -> None:
    versions = BACKEND / "alembic" / "versions"
    revs: dict[str, str | None] = {}
    for f in versions.glob("*.py"):
        t = f.read_text(encoding="utf-8", errors="replace")
        r = re.search(r'^revision: str = "([^"]+)"', t, re.M)
        d = re.search(r'^down_revision: Union\[str, None\] = (?:"([^"]+)"|None)', t, re.M)
        if r:
            revs[r.group(1)] = d.group(1) if (d and d.group(1)) else None
    downs = {v for v in revs.values() if v}
    heads = [r for r in revs if r not in downs]
    dangling = [d for d in downs if d not in revs]
    check(len(heads) == 1, "migrations: exactly one head", f"heads={heads}")
    check(heads == [manifest["expected_migration_head"]],
          "migrations: head matches manifest", f"{heads} vs {manifest['expected_migration_head']}")
    check(not dangling, "migrations: no dangling down_revisions", str(dangling))
    check(len(revs) == manifest["migration_chain_length"],
          "migrations: chain length", f"{len(revs)} vs {manifest['migration_chain_length']}")


def verify_dependencies() -> None:
    req = (BACKEND / "requirements.txt").read_text()
    check("PyYAML==" in req, "deps: PyYAML pinned in requirements.txt")
    check(re.search(r"composio", req) is not None,
          "deps: composio documented (optional extra)")


def verify_no_silent_degradation() -> None:
    scanner = (BACKEND / "app" / "services" / "supreme" / "scanner.py").read_text()
    check("SupremeConfigError" in scanner and "raise SupremeConfigError" in scanner,
          "supreme: load_map raises instead of fabricating defaults")
    # the OLD silent pattern (return {} right after an ImportError on yaml) must be gone
    bad = re.search(r"except ImportError:\s*\n\s*logger\.error[^\n]*\n\s*return \{\}", scanner)
    check(bad is None, "supreme: no silent 'return {}' on missing PyYAML")

    tools = (BACKEND / "app" / "services" / "tools" / "__init__.py").read_text()
    check('logger.error("tools: composio' in tools,
          "composio: misconfig (key set, lib missing) logs ERROR, not a quiet skip")


def verify_destructive_wildcard(run: bool) -> None:
    if not run:
        print("[skip] governance regression (pass --full to run)")
        return
    r = subprocess.run([sys.executable, "-m", "pytest",
                        "tests/test_governance.py", "-q",
                        "-k", "wildcard or destructive"],
                       cwd=str(BACKEND), capture_output=True, text=True)
    check(r.returncode == 0, "governance: destructive scopes denied under module wildcard",
          r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")


def verify_full_suite(run: bool, manifest: dict) -> None:
    if not run:
        print("[skip] full pytest suite (pass --suite to run)")
        return
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=str(BACKEND), capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    exp = manifest["expected_tests"]
    ok = r.returncode == 0 and f"{exp['passed']} passed" in r.stdout
    check(ok, f"suite: {exp['passed']} passed / {exp['failed']} failed", tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/istanbul",
                    help="git ref to verify (default origin/istanbul; use integration/verify-all for a pre-merge dry run)")
    ap.add_argument("--full", action="store_true", help="run the governance regression subset")
    ap.add_argument("--suite", action="store_true", help="run the entire pytest suite")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"missing manifest: {MANIFEST}")
        return 2
    manifest = json.loads(MANIFEST.read_text())

    print(f"== verifying ref '{args.ref}' against {MANIFEST.name} ==\n")
    verify_git(manifest, args.ref)
    verify_migrations(manifest)
    verify_dependencies()
    verify_no_silent_degradation()
    verify_destructive_wildcard(args.full or args.suite)
    verify_full_suite(args.suite, manifest)

    failed = [lbl for ok, lbl in _results if not ok]
    print("\n" + ("=" * 60))
    if failed:
        print(f"RESULT: FAIL ({len(failed)} check(s))")
        for lbl in failed:
            print(f"  - {lbl}")
        return 1
    print(f"RESULT: PASS ({len(_results)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
