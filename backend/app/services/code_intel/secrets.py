"""Pre-embedding secret scrubbing.

Runs on every chunk BEFORE it is embedded or stored — embeddings and DB rows
cannot be un-shipped. Hard secrets (private keys) drop the whole chunk; softer
matches (cloud keys, tokens, db-creds, inline `secret = "..."`) are redacted in
place. A conservative high-entropy heuristic catches unlabeled secrets without
mangling ordinary identifiers.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# Presence of a private-key block => drop the entire chunk.
_HARD_DROP = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")

# (label, pattern) — matched text is replaced with <REDACTED:label>.
_REDACT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws-akia", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("gcp-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),  # incl. sk-proj-/sk-svcacct-
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    ("db-url-creds", re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
        r"[^:@\s/]+:[^@\s/]+@")),
    ("inline-secret", re.compile(
        r"(?i)(?:private_key|secret_key|secret|api[_\-]?key|access[_\-]?key|"
        r"password|passwd|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    # Long hex runs (md5/sha1/sha256-shaped): catches single-case hex secrets
    # (session keys, HMACs, Mailgun-style keys) the entropy sweep misses. Over-
    # redacts commit SHAs/checksums — an acceptable trade on a secret-sensitive
    # code index.
    ("hex-blob", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_\-]{24,}")
_ENTROPY_THRESHOLD = 4.2


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_secretish(tok: str) -> bool:
    """Treat a high-entropy token as a secret if it has the shape of one — base64
    punctuation, mixed-case-with-digits, OR a single-case alphanumeric run with
    digits (many providers issue lowercase- or uppercase-only tokens)."""
    if "+" in tok or "/" in tok or "=" in tok:
        return True
    has_digit = any(c.isdigit() for c in tok)
    has_lower = any(c.islower() for c in tok)
    has_upper = any(c.isupper() for c in tok)
    if has_digit and has_lower and has_upper:
        return True
    return has_digit and (has_lower != has_upper)  # single-case alnum with digits


def redact(content: str) -> tuple[str, bool, int]:
    """Return ``(scrubbed_content, hard_dropped, redaction_count)``.

    ``hard_dropped=True`` => the caller MUST drop the whole chunk (never embed)."""
    if _HARD_DROP.search(content):
        return "", True, 1

    redactions = 0
    out = content
    for label, pat in _REDACT_PATTERNS:
        out, n = pat.subn(f"<REDACTED:{label}>", out)
        redactions += n

    def _sweep(m: re.Match) -> str:
        nonlocal redactions
        tok = m.group(0)
        if _looks_secretish(tok) and _shannon(tok) >= _ENTROPY_THRESHOLD:
            redactions += 1
            return "<REDACTED:high-entropy>"
        return tok

    out = _TOKEN_RE.sub(_sweep, out)
    return out, False, redactions
