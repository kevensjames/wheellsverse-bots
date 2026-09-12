#!/usr/bin/env python3
"""Hardened deploy-skill suggester (UserPromptSubmit) — FALSE-POSITIVE fix.

Defect being corrected: the vendored plugin hook
`…/plugins/cache/claude-plugins-official/{data,data-engineering,astronomer-data-agents}/…/
skills/airflow/hooks/airflow-skill-suggester.sh` lowercases the ENTIRE raw prompt
and runs an unanchored, per-line `grep -E` for patterns like `deploy.*pipeline`,
`deploy.*dag`, `deploy.*airflow`, `astro deploy`. It therefore fires on quoted
mission prose, documentation, markdown/code blocks, negations ("do not deploy",
"nothing deployed", "deployed services"), and filenames — any line that merely
mentions the words. That is a false positive: a *description* of deployment is not
a *request* to deploy.

This replacement decides structurally and FAILS CLOSED:
  * fenced code blocks, inline code, and blockquotes are stripped (quoted/markdown
    text cannot trigger);
  * a suggestion requires an explicit operator deploy COMMAND — the literal
    `astro deploy` CLI (but not the phrase "astro deploy commands", which is
    documentation) OR an imperative "deploy/redeploy/ship/release/roll out …
    <dag|dags|airflow|pipeline|image|to astro|to production>";
  * negations and deployment-STATE references ("do not/don't/never deploy",
    "no deployment", "nothing deployed", "deployed services") never trigger;
  * anything ambiguous returns False (fail closed).

CRITICAL: this is an ADVISORY suggester. A match only prints a skill hint to
stdout. It performs no deployment, upload, credential access, or any external
effect, and it grants no authority — real deployment remains behind KAI's own
owner-authorization and approval gates (and is not authorized here). The function
is pure (string -> bool); it does no I/O.
"""
from __future__ import annotations

import re
import sys

_NEG = r"(do not|don't|do n't|never|no\b|not\b|nothing|without|cannot|can't|stop|avoid|instead of|rather than|disable|prevent)"
_CLI = re.compile(r"\bastro\s+deploy\b", re.I)
_DOC_CLI = re.compile(r"\bastro\s+deploy\s+command", re.I)  # "astro deploy commands" = docs
_IMPERATIVE = re.compile(
    r"(?:^|[.;:!]\s+|\bplease\s+|\bnow\s+)(deploy|redeploy|ship|release|roll\s*out)\b"
    r"[^.\n]{0,60}\b(dag|dags|airflow|pipeline|image|to\s+astro|to\s+prod|to\s+production|astro)\b",
    re.I,
)
_STATE = re.compile(r"\bdeployed\s+services\b|\bnothing\s+deployed\b|\bno\s+deployment\b", re.I)


def _strip_noncommand(text: str) -> str:
    """Remove fenced code blocks, inline code, and blockquote lines — quoted /
    markdown content must not be treated as an operator command."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(">"))


def _negated(low: str) -> bool:
    return bool(
        re.search(_NEG + r"[^.\n]{0,30}\bdeploy", low)
        or re.search(r"\bdeploy\w*\b[^.\n]{0,24}" + _NEG, low)
        or _STATE.search(low)
    )


def should_suggest_deploy(prompt: str) -> bool:
    """True only if the prompt contains an explicit, non-negated operator deploy
    command. Pure; fails closed."""
    if not prompt or not prompt.strip():
        return False
    for raw in _strip_noncommand(prompt).splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if _negated(low):
            continue
        if _CLI.search(line) and not _DOC_CLI.search(line):
            return True
        if _IMPERATIVE.search(line):
            return True
    return False


_SUGGESTION = (
    "Deployment command detected. Consider the `/data:deploying-airflow` skill for "
    "Astro/Airflow deploy operations. (Advisory only — this grants no authority and "
    "performs no deployment; KAI's owner-authorization + approval gates still apply.)"
)


def main() -> int:
    prompt = sys.stdin.read()
    if should_suggest_deploy(prompt):
        print(_SUGGESTION)
    return 0  # never blocks; advisory only


if __name__ == "__main__":
    raise SystemExit(main())
