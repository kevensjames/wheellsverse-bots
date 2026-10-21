#!/usr/bin/env python3
"""KAI governance PreToolUse guard for the Bash tool.

Turns recurring incidents from the KAI governed-ops work into deterministic guardrails.
Wired in .claude/settings.json as a PreToolUse hook on the Bash matcher. Reads the hook JSON
on stdin ({"tool_name","tool_input":{"command":...}}); exit 2 BLOCKS (reason on stderr), exit 0
allows. FAILS OPEN: any parse/logic error -> exit 0, so a bug here can never brick the session.

Checks (P0), each maps to a real incident/constraint:
  1. no ad-hoc code signing / TCC grants   (permanent desktop-bridge constraint)
  2. no bearer token in a URL                (PR#82 "JWT in query" class)
  3. no secret file piped to the network     ("secrets never leave the box")
  4. KAI_*_ENABLED must stay off             (dormant-by-default; override: .kai-allow-enable)
  5. no deploy / don't touch the soak        (only while .kai-soak-active exists)

Markers live at the repo root and are gitignored, so a human toggles them deliberately.
"""
import json
import os
import re
import sys


def _block(reason: str):
    sys.stderr.write("KAI bash guard: " + reason + "\n")
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail open
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)

    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    def marker(name):
        return os.path.exists(os.path.join(root, name))

    low = cmd.lower()

    # 1. ad-hoc signing + TCC ----------------------------------------------------------------
    if "codesign" in low and re.search(r"(?:-s|--sign)\s+['\"]?-['\"]?(\s|$)", cmd):
        _block("ad-hoc code signing is forbidden (a rebuild changes the cdhash and breaks any TCC "
               "grant). Use a Developer ID identity via sign_developer_id.sh.")
    if re.search(r"\btccutil\b", cmd) or re.search(r"\bTCC\.db\b", cmd):
        _block("TCC must not be granted/reset from a command. TCC to Terminal/Python/Node/Claude "
               "is a permanent no.")

    # 2. bearer token in a URL ---------------------------------------------------------------
    if re.search(r"[a-z]+://[^\s'\"]*[?&](?:access_token|token|jwt|api[_-]?key|apikey|bearer|sig|signature)=",
                 cmd, re.I):
        _block("a credential is in a URL query string. Never put bearer tokens/JWTs/API keys in a "
               "URL (they leak to logs/history/referrers). Use a header or short-lived auth.")

    # 3. secret file -> network --------------------------------------------------------------
    sender = re.search(r"\b(curl|wget|scp|rsync|ncat|nc|ftp|http|https)\b", low)
    secret_file = re.search(r"(@\S*\.env\b|/\.env(\.|\b)|/\.ssh/|\bid_rsa\b|\.p12\b|\.pem\b|"
                            r"Keychains?/|\.aws/credentials|\.gnupg/)", cmd)
    if sender and secret_file and not marker(".kai-allow-egress"):
        _block("this looks like sending a secret file over the network. Refused. If intentional, "
               "create .kai-allow-egress at the repo root.")

    # 4. flag must stay off ------------------------------------------------------------------
    if not marker(".kai-allow-enable"):
        if re.search(r"\bKAI_[A-Z0-9_]*ENABLED\s*=\s*(?:true|1|True)\b", cmd) or \
           re.search(r"variables\s+--set\s+['\"]?KAI_[A-Z0-9_]*ENABLED=(?:true|1)", cmd, re.I):
            _block("refusing to set a KAI_*_ENABLED flag on. These stay dormant-by-default. If this "
                   "is a deliberate, reviewed enablement, create .kai-allow-enable at the repo root.")

    # 5. no deploy / soak untouchable (only while a soak is active) --------------------------
    if marker(".kai-soak-active"):
        if re.search(r"\brailway\s+(up|down|redeploy|restart)\b", low):
            _block("a soak is active (.kai-soak-active): no railway deploy/teardown until it finishes.")
        if re.search(r"\bgit\s+push\b", low) and re.search(r"production", low):
            _block("a soak is active (.kai-soak-active): no push to production during the soak.")
        if "costaging" in low or "kai-costaging" in low:
            _block("a soak is active: do not touch the soak service (costaging). Leave it untouched "
                   "until the 72h soak completes.")

    # 6. shared git stash stack (worktrees share it — bare stash/pop can grab another session's) -
    if re.search(r"\bgit\s+stash\s+pop\b", low):
        _block("`git stash pop` on a SHARED stash stack can pop another worktree/session's entry. "
               "Use `git stash apply <sha>` after finding your entry by tag, or a WIP commit.")
    if re.search(r"\bgit\s+stash\b(?!\s+(?:push|list|show|apply|drop|clear|branch))", low):
        _block("bare `git stash` on a SHARED stack is unsafe. Use `git stash push -u -m '<tag>'` "
               "(then apply by sha), or a temporary WIP commit.")

    # 7. production device enrollment (governed device scope; zero prod devices) ---------------
    if re.search(r"device.{0,24}enroll", low) and re.search(r"\bprod|production\b", low) \
       and not marker(".kai-allow-device-enroll"):
        _block("refusing a production device-enrollment call. Device enrollment is a deliberate, "
               "gated operator action (zero production devices is an invariant).")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail open, always
