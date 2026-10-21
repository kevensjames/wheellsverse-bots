#!/usr/bin/env python3
"""KAI ops guard — PreToolUse (Bash). Companion to kai_bash_guard.py.

kai_bash_guard.py encodes SAFETY constraints (things that must never happen). This file encodes
CORRECTNESS traps: operations that appear to succeed while doing nothing, or that produce a
confident-but-wrong conclusion. Every rule below is a real incident from the 2026-09-10/11
governed-ops sessions, with the cost noted.

Most rules WARN (stdout, exit 0) rather than block: the operation is usually legitimate, and the
failure is believing the wrong thing about its effect. Two rules block, because their failure mode
is acting on the wrong target.

Reads hook JSON on stdin. exit 2 BLOCKS (reason on stderr); exit 0 allows (stdout = reminder).
FAILS OPEN: any error -> exit 0, so a bug here can never brick the session.

Override markers (gitignored, a human flips them deliberately), matching the existing convention:
  .kai-allow-inert-set   permit a --skip-deploys set without the staleness warning
  .kai-allow-blind-up    permit an upload deploy that does not name its target service
"""
import json
import os
import re
import sys

ENABLED_FLAG = r"[A-Z][A-Z0-9_]*_ENABLED"       # built as a pattern, never as a literal assignment


def _block(reason: str):
    sys.stderr.write("KAI ops guard: " + reason + "\n")
    sys.exit(2)


def _is_invocation(cmd: str, prog: str, sub: str = "") -> bool:
    """True only if `prog [sub]` is actually being RUN, not merely mentioned.

    The companion guard matches raw substrings, so a grep pattern, an echo, or a quoted string
    trips it as hard as a real command — that misfired twice in one session and blocked read-only
    inspection. Here a match must sit at a command position: start of line, or after a shell
    operator (; && || | newline), optionally preceded by env assignments.
    """
    tail = r"\s+" + sub + r"\b" if sub else r"\b"
    pattern = r"(?:^|[\n;]|&&|\|\||\|)\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*" + prog + tail
    for m in re.finditer(pattern, cmd):
        # Ignore a match that sits inside a quoted argument (a pattern being searched for).
        prefix = cmd[:m.start()]
        if prefix.count("'") % 2 == 0 and prefix.count('"') % 2 == 0:
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)

    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    def marker(name):
        return os.path.exists(os.path.join(root, name))

    notes = []

    # 1. --skip-deploys stores a value the RUNNING container never sees -------------------------
    #    Cost: hit three times. A cron run inherits its deployment's env SNAPSHOT and does not
    #    re-read current variables — proven when a briefing run still attempted an HTTP send 63
    #    minutes after the flag was stored false. The stored value looked like containment and
    #    was not. The fix each time was to force a new deployment.
    if "--skip-deploys" in cmd and not marker(".kai-allow-inert-set"):
        turning_off = re.search(r"--set\s+['\"]?" + ENABLED_FLAG + r"=(?:false|0)", cmd, re.I)
        notes.append(
            "--skip-deploys STORES the variable; the running container keeps its old environment. "
            "A Railway cron run inherits its deployment's env snapshot and does not re-read "
            "current variables."
            + (" You are storing a *_ENABLED=false, which reads as containment — it is NOT in "
               "effect until a new deployment is created. Verify against a real run before "
               "reporting it contained." if turning_off else
               " Force a deployment if the value must take effect."))

    # 2. head/tail on a live log stream -> a conclusion drawn from the WRONG end -----------------
    #    Cost: a verdict script reported the right answer from a stale line (audit id 286, a run
    #    that predated the test window) because capture began 18s before the real run finished.
    #    Right answer, wrong evidence — indistinguishable from luck.
    if re.search(r"\b(?:railway|docker|kubectl|heroku|flyctl|journalctl)\b[^|]*\blogs?\b[^|]*\|\s*head\b", cmd):
        notes.append(
            "piping a log stream into `head` yields the OLDEST buffered lines and SIGPIPEs the "
            "producer. If you are checking whether a recent run did X, this shows you an earlier "
            "run. Bound the capture by time and assert you observed the specific run (e.g. an id "
            "strictly greater than the last known one) before drawing a verdict.")

    # 3. zsh traps that silently mangle a command ----------------------------------------------
    #    Cost: three separate failures in one session.
    if re.search(r"--(?:include|exclude)=\*[.\w]", cmd) and not re.search(
            r"--(?:include|exclude)=(['\"])\*", cmd):
        notes.append(
            "unquoted --include=*.ext : zsh expands this before the program sees it and aborts "
            "with 'no matches found' when nothing matches in the CWD. Quote it: --include='*.py'.")
    # Unbraced only: ${var}:rest is the CORRECT form and must not warn (braces end the name).
    if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]", cmd):
        notes.append(
            "$var: followed by a letter is a zsh PARAMETER MODIFIER (:r :e :h :t), not a literal "
            "colon. This silently mangled a git refspec. Brace it: ${var}:rest.")
    if re.search(r"-m\s+\"[^\"]*`", cmd):
        notes.append(
            "a backtick inside a double-quoted -m message is COMMAND SUBSTITUTION in zsh — the "
            "word is executed and removed from the message. Use a -F file, or single quotes.")

    # 4. an upload deploy that does not name its target ----------------------------------------
    #    Cost: `railway link` failed SILENTLY, leaving the CLI pointed at another project, and an
    #    upload began pushing one app into an unrelated project before it was killed. Naming the
    #    service makes the target explicit and reviewable.
    if _is_invocation(cmd, "railway", "up") and not re.search(r"--service\b|\s-s\b", cmd) \
            and not marker(".kai-allow-blind-up"):
        _block(
            "this upload deploy does not name a --service. `railway link` can fail SILENTLY and "
            "leave the CLI pointed at a DIFFERENT project; an unnamed upload then goes wherever "
            "the link happens to point (this nearly shipped one app into an unrelated project). "
            "Pass --service <name>, and assert `railway status` shows the expected project first.")

    # 5. force-push to a deploy branch ----------------------------------------------------------
    if _is_invocation(cmd, "git", "push") and re.search(r"(?:--force(?!-with-lease)|(?<![\w-])-f\b)", cmd) \
            and re.search(r"\b(?:production|main|master)\b", cmd):
        _block(
            "force-push to a deploy branch. production is protected (force pushes and deletions "
            "prohibited) and rewriting it discards history other clones depend on. If you must "
            "rewrite, do it on a feature branch.")

    # 6. trusting a self-reported build identity ------------------------------------------------
    #    Cost: production /api/health reports git_sha 5e767a4 while actually running b486a138 —
    #    the SHA comes from an env var nobody updates. Any check trusting it concludes falsely.
    if re.search(r"git_sha|source_sha|build_sha", cmd) and re.search(r"health|/api/|curl", cmd, re.I):
        notes.append(
            "git_sha from a health endpoint is NOT trustworthy here: App A deploys by upload and "
            "the SHA comes from a stale env var (production has reported a SHA two releases old "
            "while running the current one). Verify provenance with deploy_id + build_time + the "
            "presence of a feature the release actually added.")

    if notes:
        sys.stdout.write("KAI ops guard:\n- " + "\n- ".join(notes) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail open, always
