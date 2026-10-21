#!/usr/bin/env python3
"""Self-test for kai_ops_guard.py. Zero framework, mirrors test_kai_hooks.py.

Run: python3 scripts/hooks/test_kai_ops_guard.py

Each case asserts the guard's OUTCOME (block / warn / silent) for a command. The negative cases
matter as much as the positive ones: a guard that fires on a mention rather than an invocation
blocks legitimate work, which is exactly what happened twice in one session with the companion
guard's substring matching.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kai_ops_guard.py")
BLOCK, WARN, SILENT = "block", "warn", "silent"

results = []


def run(cmd: str, root: str):
    p = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                       capture_output=True, text=True,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": root})
    if p.returncode == 2:
        return BLOCK, p.stderr
    return (WARN, p.stdout) if p.stdout.strip() else (SILENT, "")


def expect(name, cmd, want, root, needle=""):
    got, out = run(cmd, root)
    ok = got == want and (needle.lower() in out.lower() if needle else True)
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"         wanted {want}{' + ' + needle if needle else ''}, got {got}: {out.strip()[:150]}")


def main():
    clean = tempfile.mkdtemp(prefix="kai-ops-clean-")
    allow_inert = tempfile.mkdtemp(prefix="kai-ops-inert-")
    open(os.path.join(allow_inert, ".kai-allow-inert-set"), "w").close()
    allow_up = tempfile.mkdtemp(prefix="kai-ops-up-")
    open(os.path.join(allow_up, ".kai-allow-blind-up"), "w").close()

    print("kai_ops_guard self-test\n")

    # 1. --skip-deploys staleness (hit 3x)
    expect("skip-deploys warns about the stale running env",
           "railway variables --service kai-prod --set 'FOO=1' --skip-deploys", WARN, clean, "snapshot")
    expect("skip-deploys turning a flag OFF names the containment trap",
           "railway variables --service c --set 'KAI_HOLDING_DELIVERY_ENABLED=false' --skip-deploys",
           WARN, clean, "contained")
    expect("skip-deploys silent when the override marker exists",
           "railway variables --service c --set 'FOO=1' --skip-deploys", SILENT, allow_inert)

    # 2. log stream truncation (produced a right-answer-wrong-evidence verdict)
    expect("logs piped into head warns about the oldest lines",
           "railway logs --service kai-briefing-cron | head -80", WARN, clean, "oldest")
    expect("logs without head is silent",
           "railway logs --service kai-briefing-cron > /tmp/x", SILENT, clean)

    # 3. zsh traps (three separate failures)
    expect("unquoted --include=*.py warns",
           'grep -rn "foo" --include=*.py .', WARN, clean, "quote it")
    expect("quoted --include is silent",
           "grep -rn 'foo' --include='*.py' .", SILENT, clean)
    expect("$var: modifier warns",
           'git push origin "$b:refs/heads/$b"', WARN, clean, "modifier")
    expect("braced ${var}: is silent",
           'git push origin "${b}:refs/heads/${b}"', SILENT, clean)
    expect("backtick inside -m warns",
           'git commit -m "records `customer` provenance"', WARN, clean, "substitution")

    # 4. unnamed upload deploy (nearly shipped an app into another project)
    expect("upload deploy without --service BLOCKS",
           "railway up --detach", BLOCK, clean, "silently")
    expect("upload deploy naming its service is allowed",
           "railway up --service kai-prod --detach", SILENT, clean)
    expect("upload deploy allowed with the override marker",
           "railway up --detach", SILENT, allow_up)

    # 4b. THE FALSE-POSITIVE FIX: a MENTION is not an invocation.
    #     The companion guard blocked read-only inspection twice because it substring-matched.
    expect("grepping FOR the deploy string is NOT blocked",
           "grep -rn 'railway up' scripts/hooks/", SILENT, clean)
    expect("echoing the deploy string is NOT blocked",
           'echo "run railway up to deploy"', SILENT, clean)
    expect("a comment mentioning it is NOT blocked",
           "ls -la   # later we railway up --detach", SILENT, clean)

    # 5. force-push to a deploy branch
    expect("force push to production BLOCKS",
           "git push --force origin HEAD:production", BLOCK, clean, "protected")
    expect("force-with-lease to a feature branch is allowed",
           "git push --force-with-lease origin fix/loop-repairs", SILENT, clean)

    # 6. self-reported build identity is not provenance
    expect("reading git_sha from health warns",
           "curl -s https://app.wheellsverse.com/api/health | grep git_sha", WARN, clean, "stale env var")

    # benign
    expect("an ordinary command is silent", "ls -la && git status", SILENT, clean)

    print(f"\nKAI OPS GUARD TESTS: {sum(results)}/{len(results)} — "
          f"{'PASS' if all(results) else 'FAIL'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
