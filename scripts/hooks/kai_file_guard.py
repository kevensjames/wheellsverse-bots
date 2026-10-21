#!/usr/bin/env python3
"""KAI governance PreToolUse guard for Write/Edit.

Wired in .claude/settings.json as a PreToolUse hook on the "Write|Edit|MultiEdit" matcher.
Reads the hook JSON on stdin; exit 2 BLOCKS (reason on stderr), exit 0 allows. FAILS OPEN.

Checks (P0):
  A. KAI_*_ENABLED must stay off in written/edited config  (override: .kai-allow-enable)
  B. a new *.py must not shadow a risky stdlib module        (the queue.py footgun; override: .kai-allow-shadow)
  C. no secret-shaped VALUE written into an evidence/report/doc file  ("secrets in evidence: 0")
"""
import json
import os
import re
import sys

RISKY_STDLIB = {
    "queue", "types", "string", "io", "json", "socket", "ssl", "email", "http", "select",
    "code", "test", "random", "time", "copy", "secrets", "hashlib", "logging", "abc", "enum",
    "csv", "re", "os", "sys", "typing", "asyncio", "datetime", "collections", "functools",
    "signal", "struct", "array", "queue", "token", "keyword", "operator", "platform",
}
SECRET_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|ghp_[A-Za-z0-9]{20,}|"
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")  # api key / slack / gh / aws / pem / JWT


def _block(reason: str):
    sys.stderr.write("KAI file guard: " + reason + "\n")
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    # content differs by tool: Write -> content; Edit -> new_string; MultiEdit -> edits[].new_string
    content = ti.get("content")
    if content is None:
        content = ti.get("new_string")
    if content is None and isinstance(ti.get("edits"), list):
        content = "\n".join(e.get("new_string", "") for e in ti["edits"] if isinstance(e, dict))
    content = content or ""
    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    def marker(name):
        return os.path.exists(os.path.join(root, name))
    # Test files and the guards' own fixtures legitimately CONTAIN these patterns as data — the
    # flag/shadow checks target real config/modules, not fixtures.
    is_fixture = bool(re.search(r"(/hooks/|(^|/)test_[^/]*\.py$|/tests?/)", path))

    # A. flag stays off in config content
    # allow an optional `: <type>` annotation between the flag and `=` (pydantic Settings style)
    if not is_fixture and not marker(".kai-allow-enable") and \
       re.search(r"\bKAI_[A-Z0-9_]*ENABLED\b[^=\n]{0,40}=\s*(?:True|true|1)\b", content):
        _block(f"refusing to write KAI_*_ENABLED = true into {os.path.basename(path)}. Flags stay "
               f"dormant-by-default; create .kai-allow-enable to override deliberately.")

    # B. stdlib shadow for a NEW python module
    if path.endswith(".py") and not is_fixture and not marker(".kai-allow-shadow"):
        base = os.path.splitext(os.path.basename(path))[0]
        # only for a genuinely new file (Write with content and no prior existence)
        is_new = (ti.get("content") is not None) and (not os.path.exists(path))
        if is_new and base in RISKY_STDLIB:
            _block(f"'{base}.py' shadows the Python stdlib module '{base}' — anything doing "
                   f"`import {base}` may resolve to this file (a real footgun; e.g. queue.py). "
                   f"Rename it, or create .kai-allow-shadow if intentional.")

    # C. secret-shaped value into a doc/evidence/report
    if re.search(r"(docs/|evidence|report|\.md$|EVIDENCE|\.log$)", path, re.I) and SECRET_VALUE.search(content):
        _block(f"a secret-shaped value (API key / token / private key / JWT) is being written into "
               f"{os.path.basename(path)}. Secrets must never enter evidence/reports/logs. Redact it.")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
