#!/usr/bin/env python3
"""KAI Stop guard — the "don't claim done without evidence" reflex (the #1 lesson of this
engagement: a false '23/23 verified'). If the final assistant message asserts a HARD status
claim and the recent transcript shows no evidence of a passing run, block the stop ONCE with a
reminder to attach evidence or soften the claim.

Loop-safe: if stop_hook_active is set, exit 0 immediately (at most one extra turn). Fails open."""
import json
import os
import re
import sys

HARD_CLAIM = re.compile(r"\b(CERTIFIED|PRODUCTION[ -]?VERIFIED|DEPLOYED TO PRODUCTION|"
                        r"PRODUCTION[ -]?READY|ALL TESTS PASS(?:ED)?)\b")
EVIDENCE = re.compile(r"(\d+\s+passed|\bPASS\b|invariants?\s+HOLD|0\s+failed|passed,\s*0\s+failed|"
                      r"STATUS:\s|✅)", re.I)
# statuses ranked low->high; asserting one above the recorded ceiling (.kai-status) is flagged.
RANK = ["TESTED_LOCALLY", "REVIEWED_AND_PASSING_LOCALLY", "CERTIFIED_LOCALLY",
        "STAGING_VERIFIED", "PRODUCTION_VERIFIED"]


def last_assistant_and_recent(transcript_path):
    last, recent = "", []
    try:
        with open(transcript_path) as fh:
            lines = fh.readlines()[-80:]
        for ln in lines:
            try:
                o = json.loads(ln)
            except Exception:
                continue
            msg = o.get("message") if isinstance(o.get("message"), dict) else o
            role = o.get("role") or o.get("type") or (msg or {}).get("role")
            content = (msg or {}).get("content")
            text = ""
            if isinstance(content, list):
                text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            elif isinstance(content, str):
                text = content
            recent.append(text)
            if role in ("assistant",):
                last = text or last
    except Exception:
        pass
    return last, "\n".join(recent)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("stop_hook_active"):
        sys.exit(0)  # already re-entered once — never loop
    tp = data.get("transcript_path") or ""
    if not tp or not os.path.exists(tp):
        sys.exit(0)
    last, recent = last_assistant_and_recent(tp)
    if not last:
        sys.exit(0)

    # WARN-only: this reasons over free-form prose, where a hard block is too blunt (it misfires
    # on meta-discussion / negations, e.g. "a 'CERTIFIED/deployed' claim" or "not certified").
    # Emit a reminder on stdout and always allow the stop.
    reminders = []
    # skip when the token only appears negated or in a slash-enumeration (meta-discussion)
    negated = re.search(r"(?:not|never|isn'?t|aren'?t|un)\s+\w*certif|/\s*certified|certified\s*/", last, re.I)
    if HARD_CLAIM.search(last) and not EVIDENCE.search(recent) and not negated:
        reminders.append("a hard status claim (certified / production-verified / deployed / "
                         "all-tests-pass) appears with no evidence of a passing run in this turn — "
                         "attach the test/cert output or soften to what was actually verified.")
    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    try:
        ceiling = open(os.path.join(root, ".kai-status")).read().strip()
        cr = next((i for i, s in enumerate(RANK) if s in ceiling), -1)
        for i in range(len(RANK) - 1, cr, -1):
            if RANK[i] in last and i > cr >= 0 and not negated:
                reminders.append(f"the message names status '{RANK[i]}' above the recorded ceiling "
                                 f"('{ceiling}') — don't advance the label without the gate that earns it.")
                break
    except Exception:
        pass
    if reminders:
        sys.stdout.write("KAI stop reminder:\n- " + "\n- ".join(reminders) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
