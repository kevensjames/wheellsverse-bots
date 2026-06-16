"""Scan: runtime state / log files that got committed to git.

Pattern origin: in the SUPREMA demo session a `git add .` accidentally
vacuumed up 981 lines of:

  - data/stan_store/sessions/.stan_storage_state.json  (Playwright session
                                                        cookies — credentials!)
  - tools/ig_unfollow/progress.json
  - tools/ig_unfollow/session.json
  - tools/ig_unfollow/run.log
  - tools/ig_unfollow/scheduler.log

Files matching these classes should never be in a repo:
  - runtime logs (rotated; bloat history; sometimes secrets)
  - session/auth state (cookies, tokens — secrets!)
  - progress / queue state (race conditions if multiple operators)
  - generated artifacts (videos, large binaries)
  - local DBs (*.sqlite, *.db) unless they're seed data

Detection: iterate `git ls-files`; check each path against curated
patterns. Report any match as a finding with a fix payload that tells
the fixer which file + which .gitignore pattern to add.

Conservative whitelist of EXEMPT directories so we don't flag legit
tracked files: tests/, docs/, fixtures/, samples/, examples/, README.md
adjacent state files, anything with 'test' or 'sample' in the path.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# (filename pattern, gitignore pattern to add)
RUNTIME_STATE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Logs
    (re.compile(r".*\.log$"),                     "**/*.log",                       "log file"),
    (re.compile(r".*\.log\.\d+$"),                "**/*.log.*",                     "rotated log"),
    # Session / auth state
    (re.compile(r".*session\.json$"),             "**/session.json",                "session state (may contain auth)"),
    (re.compile(r".*storage_state\.json$"),       "**/*storage_state.json",         "Playwright storage state (cookies/auth)"),
    (re.compile(r".*\.session$"),                 "**/*.session",                   "session file"),
    # Progress / queue state
    (re.compile(r".*progress\.json$"),            "**/progress.json",               "runtime progress"),
    (re.compile(r".*queue\.json$"),               "**/queue.json",                  "runtime queue"),
    (re.compile(r".*\.lock$"),                    "**/*.lock",                      "lock file"),
    (re.compile(r".*\.pid$"),                     "**/*.pid",                       "process ID file"),
    # Local DBs (excluding migrations/seeds)
    (re.compile(r".*\.sqlite3?$"),                "**/*.sqlite",                    "SQLite database"),
    (re.compile(r".*\.db$"),                      "**/*.db",                        "database file"),
    # Common cache dirs
    (re.compile(r"\.pytest_cache/.+"),            ".pytest_cache/",                 "pytest cache"),
    (re.compile(r"\.mypy_cache/.+"),              ".mypy_cache/",                   "mypy cache"),
    (re.compile(r"__pycache__/.+"),               "__pycache__/",                   "Python bytecode cache"),
    # Env / secrets — but NOT templates (.env.example, .env.sample, etc.
    # are intentionally committed as documentation)
    (re.compile(r"(^|/)\.env$"),                                                ".env",                       "env file (likely secrets)"),
    (re.compile(r"(^|/)\.env\.(local|development|prod|production|staging|test)$"), ".env.local",               "env override (likely secrets)"),
    (re.compile(r".*\.pem$"),                                                   "**/*.pem",                   "PEM cert/key (secret!)"),
    (re.compile(r".*credentials.*\.json$"),                                     "**/*credentials*.json",      "credentials file (secret!)"),
]

# Files that SUPERFICIALLY match a pattern but are actually safe to commit
# — templates, examples, fixtures, etc.
EXEMPT_FILENAME_SUFFIXES = (
    ".example", ".sample", ".template", ".dist", ".sample.json",
    ".example.json", ".template.json",
)

# Exempt path substrings — these dirs may legitimately track state-shaped
# files (test fixtures, documentation samples)
EXEMPT_PATH_SUBSTRINGS = (
    "/tests/", "/test/", "/__tests__/",
    "/fixtures/", "/samples/", "/examples/",
    "/seed/", "/migrations/",
    "test_", "_test.", "_sample.",
)


def _git_tracked_files(project: Path) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "ls-files"],
            cwd=str(project),
            capture_output=True, text=True, timeout=30, check=False,
        )
        return r.stdout.splitlines()
    except Exception:
        return []


def _is_exempt(path_str: str) -> bool:
    if any(s in path_str for s in EXEMPT_PATH_SUBSTRINGS):
        return True
    # Templates / examples / samples — never flag these
    if any(path_str.endswith(suffix) for suffix in EXEMPT_FILENAME_SUFFIXES):
        return True
    # File whose basename CONTAINS '.example' or '.sample' anywhere
    # (.env.example.json, foo.sample.txt, etc.)
    basename = path_str.rsplit("/", 1)[-1]
    if any(marker in basename for marker in (".example", ".sample", ".template", ".dist")):
        return True
    return False


def _read_gitignore(project: Path) -> str:
    gi = project / ".gitignore"
    if gi.is_file():
        try:
            return gi.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""


def _already_ignored(path: str, gitignore: str) -> bool:
    """Heuristic: if the gitignore already contains a pattern matching
    this path, skip (the operator already knows to keep it out)."""
    # Most relevant: the exact filename, the directory, or a glob
    name = path.rsplit("/", 1)[-1]
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    needle_list = [path, name, f"{parent}/", f"**/{name}"]
    for line in gitignore.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s in needle_list:
            return True
    return False


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    if not (project / ".git").exists():
        return []
    findings: list[dict] = []
    files = _git_tracked_files(project)
    if not files:
        return []
    gitignore = _read_gitignore(project)
    seen_patterns: set[str] = set()

    for path in files:
        if _is_exempt(path):
            continue
        for pat, gi_rule, descr in RUNTIME_STATE_PATTERNS:
            if not pat.search(path):
                continue
            # Already ignored — but still tracked. That's weird, but we
            # don't auto-fix because the operator may have explicitly
            # `git add -f`'d it for a reason.
            if _already_ignored(path, gitignore):
                continue

            sev = "high" if any(
                k in descr.lower() for k in ("secret", "auth", "credentials")
            ) else "medium"
            findings.append({
                "severity": sev,
                "location": path,
                "evidence": f"tracked {descr}",
                "fix_payload": {
                    "file": path,
                    "gitignore_pattern": gi_rule,
                    "description": descr,
                },
            })
            # Don't apply multiple patterns to the same file
            seen_patterns.add(gi_rule)
            break

    return findings
