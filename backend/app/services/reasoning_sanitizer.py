"""Reasoning-output sanitizer (§24) — the authoritative BACKEND boundary.

Removes model reasoning scratchpads (``<think>…</think>`` and variants) before any
assistant-visible text crosses an externally-observable sink: SSE deltas, buffered
API responses, DB persistence of assistant message content, and TTS. The frontend
strip (kai-nexus-pulse.js ``stripReasoning`` / kai-presence.js ``_stripReason``)
remains as defense-in-depth; this module makes the backend authoritative and matches
the frontend semantic EXACTLY (no frontend/backend divergence):

  * a paired ``<think>…</think>`` block is ALWAYS removed;
  * an UNCLOSED trailing block is SUPPRESSED mid-stream (a partial scratchpad must
    never flash) but PRESERVED on finalize — a lone literal ``<think>`` in a
    completed answer is user content (e.g. KAI explaining tag syntax), not reasoning.

Two forms:
  * :func:`strip_reasoning` — stateless full-buffer, for buffered / final / TTS paths.
  * :class:`StreamingReasoningSanitizer` — stateful, chunk-boundary-safe, for the SSE
    delta path (correctly handles a tag split across chunks, e.g. ``"<thi" + "nk>"``).

Tags matched (attribute-tolerant on the open tag): think, thinking, reasoning,
scratchpad, reflection.
"""
from __future__ import annotations

import re

_TAGS = ("think", "thinking", "reasoning", "scratchpad", "reflection")
_ALT = "|".join(_TAGS)

# Paired block (non-greedy, dotall), backreference so the close matches the open tag.
_CLOSED_RE = re.compile(r"<(" + _ALT + r")(?:\s[^>]*)?>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
# Unclosed trailing block: an open tag through end-of-text.
_OPEN_TRAILING_RE = re.compile(r"<(" + _ALT + r")(?:\s[^>]*)?>.*$", re.IGNORECASE | re.DOTALL)
# A complete open tag anchored at the start of a buffer.
_OPEN_AT_START = re.compile(r"^<(" + _ALT + r")(?:\s[^>]*)?>", re.IGNORECASE)


def strip_reasoning(text, finalized: bool = True) -> str:
    """Stateless strip. ``finalized=True`` (default) keeps a lone literal open tag;
    ``finalized=False`` also removes an unclosed trailing block (mid-stream behavior)."""
    if text is None:
        return ""
    out = _CLOSED_RE.sub("", str(text))
    if not finalized:
        out = _OPEN_TRAILING_RE.sub("", out)
    return out


def _open_prefix_possible(s: str) -> bool:
    """``s`` starts with '<' and contains no '>' yet. Could it still become a reasoning
    open tag once more input arrives? Safe over-approximation: hold whenever the chars
    after '<' are a prefix of a tag name, or a full tag name followed by whitespace
    (attributes pending). Over-holding a non-tag is harmless — it resolves to literal
    text the moment '>' (or a disqualifying char) arrives; it never leaks reasoning."""
    body = s[1:]
    low = body.lower()
    # tag-name token = up to the first whitespace
    name = re.split(r"\s", low, 1)[0]
    has_ws = len(name) < len(low)
    for t in _TAGS:
        if not has_ws:
            if t.startswith(name) or name.startswith(t):
                return True
        elif name == t:  # complete tag name, whitespace seen → attributes in progress
            return True
    return False


class StreamingReasoningSanitizer:
    """Feed provider deltas through :meth:`push`; call :meth:`flush` once at end.

    ``push(delta)`` returns the safe text to emit so far (holding back anything that
    might be, or be inside, a reasoning tag). ``flush()`` returns the final remainder:
    a lone unclosed open block (or a partial tag) that turned out to be literal content
    is emitted; a properly-closed reasoning block was already dropped.

    Guarantee: for any chunking of ``text``, ``"".join(pushes) + flush()`` equals
    ``strip_reasoning(text, finalized=True)``.
    """

    def __init__(self) -> None:
        self._buf = ""            # unresolved tail (a held partial tag, or a suppressed open block)
        self._inside = False      # True once an unmatched reasoning open tag is buffered
        self._close_re = None     # close pattern for the specific open tag

    def push(self, delta: str) -> str:
        if delta:
            self._buf += delta
        return self._drain()

    def flush(self) -> str:
        # Finalize: any resolvable output, then whatever remains is literal content
        # (a lone open block is preserved, matching strip_reasoning(finalized=True)).
        out = self._drain()
        rest = self._buf
        self._buf = ""
        self._inside = False
        self._close_re = None
        return out + rest

    def _drain(self) -> str:
        emit: list[str] = []
        while self._buf:
            if self._inside:
                m = self._close_re.search(self._buf)
                if not m:
                    break  # suppress; keep the open block buffered (may be literal on flush)
                self._buf = self._buf[m.end():]  # drop the whole reasoning block incl. close
                self._inside = False
                self._close_re = None
                continue
            lt = self._buf.find("<")
            if lt == -1:
                emit.append(self._buf)
                self._buf = ""
                break
            if lt > 0:
                emit.append(self._buf[:lt])
                self._buf = self._buf[lt:]
            m = _OPEN_AT_START.match(self._buf)
            if m:
                # keep the open tag in the buffer (do NOT emit); scan for its close
                self._inside = True
                self._close_re = re.compile(r"</" + re.escape(m.group(1)) + r"\s*>", re.IGNORECASE)
                continue
            if ">" not in self._buf and _open_prefix_possible(self._buf):
                break  # incomplete potential tag — hold for more input
            # a literal '<' (not a reasoning tag): emit it and keep scanning
            emit.append(self._buf[0])
            self._buf = self._buf[1:]
        return "".join(emit)
