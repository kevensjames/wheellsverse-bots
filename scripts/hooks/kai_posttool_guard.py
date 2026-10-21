#!/usr/bin/env python3
"""KAI governance PostToolUse reminders (P1/P2). Never blocks — surfaces a short reminder on
stdout after a Write/Edit that touches a governance-sensitive file, so easy-to-forget checks
(the exact ones this engagement kept relearning) are prompted at the moment of the edit.

Wired as a PostToolUse hook on Write|Edit|MultiEdit. Fails open (any error -> silent exit 0)."""
import json
import os
import re
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    content = ti.get("content") or ti.get("new_string") or ""
    if isinstance(ti.get("edits"), list):
        content += "\n".join(e.get("new_string", "") for e in ti["edits"] if isinstance(e, dict))
    base = os.path.basename(path)
    notes = []

    if re.search(r"alembic/versions/.*\.py$", path):
        if "def downgrade" not in content:
            notes.append("migration has no downgrade() — add a reversible downgrade (or the "
                         "repo's audit-preserving no-op) before relying on rollback.")
        if re.search(r"\bDROP\s+TABLE\b", content, re.I):
            notes.append("migration DROPs a table — the KAI convention keeps audit tables on "
                         "downgrade (0008/0009). Confirm this is not an audit/records table.")

    if base in ("playwright_adapter.py", "netpolicy.py"):
        notes.append("browser egress changed — re-confirm EVERY chromium egress channel is still "
                     "gated: HTTP (context.route), WebSocket (route_web_socket), service workers "
                     "(service_workers=block), WebRTC (init-script neuter), and context.request "
                     "(never used for downloads). Missing one is how WS/SW/WebRTC each slipped once.")

    if re.search(r"certify_.*\.py$", base) and re.search(r"\bINV\[", content) and re.search(r"\+=\s*0\b", content):
        notes.append("a cert invariant counter uses `+= 0` (dead) — measure it for real or delete "
                     "it; don't print 'invariants HOLD' for a counter nothing increments.")

    if re.search(r"routers/|(^|/)main\.py$", path):
        notes.append("route registration changed — run the route-completeness/inventory test so "
                     "chat/memory/RAG/skills/trading/voice/capabilities mounts aren't silently omitted.")

    if re.search(r"(/sol/|payment|dwolla|stripe|funds[_-]?flow|money)", path, re.I):
        notes.append(f"'{base}' looks payment/SOL-related — confirm it is in scope for this mission "
                     "(the standing rule is: do not modify SOL payment files or unrelated apps).")

    if path.endswith(".py") and re.search(r"(ops/browser-ops/|backend/app/)", path) and not base.startswith("test_"):
        notes.append(f"edited {base} — run its test (e.g. the matching test_*.py) before claiming it works.")

    if notes:
        sys.stdout.write("KAI reminders for " + base + ":\n- " + "\n- ".join(notes) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
