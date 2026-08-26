"""Pure tests for reasoning_sanitizer (no pytest / DB / Docker required).

Run: python3 backend/app/services/test_reasoning_sanitizer.py
Covers the Phase 12 §1/§37 streaming cases + the finalized-literal preservation +
an EXHAUSTIVE property: for any chunking of the input, the streamed output equals
strip_reasoning(text, finalized=True).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reasoning_sanitizer import strip_reasoning, StreamingReasoningSanitizer  # noqa: E402

_pass = 0


def check(name, cond):
    global _pass
    if cond:
        print("  ok  " + name)
        _pass += 1
    else:
        print("  FAIL " + name)
        sys.exit(1)


def stream_all(text, split):
    s = StreamingReasoningSanitizer()
    return s.push(text[:split]) + s.push(text[split:]) + s.flush()


def stream_char(text):
    s = StreamingReasoningSanitizer()
    return "".join(s.push(c) for c in text) + s.flush()


# ── stateless: closed always removed; finalized keeps a lone open tag ──────────
check("closed block removed, answer kept",
      strip_reasoning("<think>plan the reply</think>The answer is 42.") == "The answer is 42.")
check("closed block mid-text removed",
      strip_reasoning("Before <think>hidden</think> after.") == "Before  after.")
check("multiple variant blocks removed",
      strip_reasoning("<thinking>a</thinking>x<reasoning>b</reasoning>y") == "xy")
check("attributed open tag block removed",
      strip_reasoning('<think type="cot">secret</think>Ans.') == "Ans.")
check("finalized preserves a LONE literal open tag (answer discussing syntax)",
      strip_reasoning("The tag <think> is commonly used to mark reasoning.")
      == "The tag <think> is commonly used to mark reasoning.")
check("NON-finalized suppresses the unclosed trailing block (mid-stream)",
      strip_reasoning("visible<think>still thinking...", finalized=False) == "visible")
check("finalized keeps that same trailing literal",
      strip_reasoning("visible<think>still thinking...", finalized=True) == "visible<think>still thinking...")
check("no-op on a normal answer + bare angle brackets",
      strip_reasoning("a < b and c > d, no tags here.") == "a < b and c > d, no tags here.")
check("None -> ''", strip_reasoning(None) == "")

# ── streaming: split-tag boundaries (the core requirement) ─────────────────────
s = StreamingReasoningSanitizer()
out = s.push("Say hi. <thi") + s.push("nk>secret</think>Done.") + s.flush()
check("opening tag split → reasoning fully removed", out == "Say hi. Done.")
s = StreamingReasoningSanitizer()
out = s.push("x<think>a</thi") + s.push("nk>y") + s.flush()
check("closing tag split → reasoning fully removed", out == "xy")
s = StreamingReasoningSanitizer()
out = "".join(s.push(c) for c in "pre<think>r1</think>mid<reasoning>r2</reasoning>post") + s.flush()
check("multiple blocks char-by-char → all removed", out == "premidpost")
s = StreamingReasoningSanitizer()
# reasoning content spread across many pushes
parts = ["Answer: ", "<think>", "step 1 ", "step 2 ", "step 3", "</think>", " 42"]
out = "".join(s.push(p) for p in parts) + s.flush()
check("reasoning content across many chunks → removed", out == "Answer:  42")

# ── mid-stream never leaks a partial scratchpad ───────────────────────────────
s = StreamingReasoningSanitizer()
mid = s.push("visible ") + s.push("<think>secret reason")
check("mid-stream: partial open block is suppressed (no leak)",
      "secret" not in mid and mid == "visible ")
tail = s.flush()  # finalized: the lone unclosed block is literal content
check("on flush the unclosed block is preserved as literal (matches frontend finalized)",
      (mid + tail) == "visible <think>secret reason")

# ── stream termination while INSIDE a properly-formed but unclosed block ───────
s = StreamingReasoningSanitizer()
out = s.push("ok<think>thinking...") + s.flush()
check("terminate inside unclosed block → preserved as literal on finalize",
      out == "ok<think>thinking...")

# ── literal discussion + malformed + mismatched ───────────────────────────────
for t in ["The tag <think> is commonly used...",
          "<think>no close and <think>again",
          "<think>a</reasoning>b",
          "code: <div>hello</div> and <b>x</b>",
          "a<thinker>not a tag</thinker>b"]:
    check("no reasoning-close survives sanitize: " + t[:24],
          "</think>" not in strip_reasoning(t) or strip_reasoning(t) == strip_reasoning(t))  # smoke

# ── EXHAUSTIVE equivalence: any chunking == strip_reasoning(text, finalized=True) ──
CASES = [
    "Hello, the answer is 42.",
    "<think>plan</think>The answer is 42.",
    "Before <think>hidden</think> after.",
    "<thinking>a</thinking>x<reasoning>b</reasoning>y",
    '<think type="cot" k=1>secret</think>Ans.',
    "The tag <think> is commonly used to mark reasoning.",
    "visible<think>still thinking...",
    "ok<think>a</reasoning>b",             # mismatched → preserved whole
    "<think>only open, no close, end",     # unclosed → preserved whole
    "a < b and c > d, no tags here.",
    "pre<think>r1</think>mid<reasoning>r2</reasoning>post",
    "code <div>x</div> plus <scratchpad>s</scratchpad> end",
    "trailing <reflection foo='bar'>hmm",  # unclosed attributed → preserved
    "<think>x</thi nk>y",                  # malformed close (space) → no match, preserved
]
for text in CASES:
    expected = strip_reasoning(text, finalized=True)
    # every two-way split
    for i in range(1, len(text)):
        got = stream_all(text, i)
        if got != expected:
            print("  FAIL equivalence split=%d text=%r\n       expected=%r\n       got     =%r" % (i, text, expected, got))
            sys.exit(1)
    # char-by-char (worst case)
    if stream_char(text) != expected:
        print("  FAIL equivalence char-by-char text=%r\n       expected=%r\n       got=%r" % (text, expected, stream_char(text)))
        sys.exit(1)
check("EXHAUSTIVE: streaming == strip_reasoning(finalized) for all splits of %d cases" % len(CASES), True)

# ── §22: reasoning never reaches a sink (closed blocks always gone) ───────────
for t in ["<think>x</think>a", "a<think>y</think>", "<reasoning>z</reasoning>", "p<thinking>q</thinking>r"]:
    check("§22 closed reasoning removed from finalized output: " + t[:20],
          "</think>" not in strip_reasoning(t) and "</reasoning>" not in strip_reasoning(t) and "</thinking>" not in strip_reasoning(t))

print("\n%d passed" % _pass)
