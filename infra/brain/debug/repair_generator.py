"""infra.brain.debug.repair_generator — file-aware, deterministic patch generator.

Replaces the placeholder-based templates in :mod:`ci_auto_fix` with structural
transforms that operate on **real source content supplied by the caller**.
Every patch produced here:

  * references an existing file (caller-supplied via :class:`FailureContext`),
  * contains zero ``<placeholder>`` strings,
  * has hunk line numbers computed from the actual content (so
    ``git apply --check`` accepts it),
  * is minimal (one transform, one location, ≤ a handful of lines changed).

When the generator cannot produce a *clean* patch with confidence
≥ :data:`MIN_GENERATOR_CONFIDENCE`, it returns ``None`` so the caller can
fall back to the template path. That bias matches the rest of the repair
pipeline: silence beats a guessed patch.

Architectural rules baked in:

  * No I/O. The caller reads files; the generator only edits strings.
  * No imports of the modules it talks about.
  * Pure-Python ``ast`` for structural location; no third-party deps.
  * Same fix-type vocabulary as :mod:`ci_auto_fix` so the two paths are
    interchangeable from the consumer's perspective.

Public API
----------

    >>> ctx = FailureContext(
    ...     test_name="infra/brain/tests/test_x.py::test_y",
    ...     error_message="...",
    ...     traceback="...",
    ...     files={"infra/brain/agents/executor.py": "<source>"},
    ...     analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    ... )
    >>> RepairGenerator().generate_patch(ctx)
    {"patch": "...", "confidence": 0.78, "fix_type": "executor_fix", ...}
"""
from __future__ import annotations

import ast
import dataclasses
import difflib
import re
from typing import Any, Optional


# ── Public taxonomy (mirrors ci_auto_fix where overlap exists) ───────────────


FIX_TYPE_PARSER:    str = "parser_fix"
FIX_TYPE_EXECUTOR:  str = "executor_fix"
FIX_TYPE_TOOL:      str = "tool_fix"
FIX_TYPE_SAFETY:    str = "safety_fix"
FIX_TYPE_CI:        str = "ci_fix"

VALID_FIX_TYPES: frozenset[str] = frozenset({
    FIX_TYPE_PARSER, FIX_TYPE_EXECUTOR, FIX_TYPE_TOOL,
    FIX_TYPE_SAFETY, FIX_TYPE_CI,
})


# ── Tunables ────────────────────────────────────────────────────────────────


MIN_GENERATOR_CONFIDENCE: float = 0.65
"""Below this, :meth:`generate_patch` returns ``None`` so the template
fallback runs instead. Aligned with ``MIN_APPLY_CONFIDENCE`` in
``ci_autonomous_repair`` (0.7) leaving a small margin for ranking."""

MAX_PATCHED_LINES: int = 12
"""Upper bound on line count of any single emitted patch. Patches that
would exceed this are downgraded to ``None``. Keeps the generator surgical."""

# Same regex shape as ``ci_autonomous_repair._PLACEHOLDER_RE``. We
# duplicate it (instead of importing) to keep the boundary at module
# level and the validator independently inspectable.
_PLACEHOLDER_RE: re.Pattern = re.compile(r"<[A-Za-z0-9_./\- ]+>")


# ── Failure context (input) ─────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class FailureContext:
    """All inputs the generator needs to produce a real patch.

    Fields
    ------
    test_name:
        Pytest node id of the failing test, e.g.
        ``infra/brain/tests/test_x.py::test_y``.
    error_message:
        Short error string (typically the exception's first line).
    traceback:
        Full traceback text. Used to locate the failing function via
        ``File "<path>", line N, in <funcname>`` markers.
    files:
        ``{absolute_or_repo_relative_path: file_content}``. The generator
        only edits files that appear in this dict — never reads from disk.
        Caller is responsible for supplying the right files (typically the
        ones named in the traceback).
    recent_history:
        Optional list of prior :class:`Fix`-shaped dicts for the same
        signature. Used only to lower confidence when a previous attempt
        already failed for the same fix-type. Empty by default.
    analysis:
        Optional dict from :func:`infra.brain.debug.ci_self_healing.analyze_ci_failure`.
        When present, the generator dispatches on its ``stage`` and
        ``reason`` fields. When absent, dispatch falls back to traceback
        parsing.
    """

    test_name: str
    error_message: str = ""
    traceback: str = ""
    files: dict[str, str] = dataclasses.field(default_factory=dict)
    recent_history: list[dict] = dataclasses.field(default_factory=list)
    analysis: Optional[dict] = None

    def stage(self) -> str:
        a = self.analysis or {}
        return str(a.get("stage") or "unknown").strip().lower() or "unknown"

    def reason(self) -> str:
        a = self.analysis or {}
        return str(a.get("reason") or "").strip()


# ── Generator ───────────────────────────────────────────────────────────────


class RepairGenerator:
    """Deterministic, file-aware patch generator.

    Stateless across calls — instantiate once per process or per call;
    either is fine. The class shape exists so future versions can carry
    config (e.g. additional transforms) without changing the API.
    """

    def __init__(
        self,
        *,
        min_confidence: float = MIN_GENERATOR_CONFIDENCE,
        max_patched_lines: int = MAX_PATCHED_LINES,
    ) -> None:
        self.min_confidence = float(min_confidence)
        self.max_patched_lines = int(max_patched_lines)

    # ── Public entry point ──────────────────────────────────────────────

    def generate_patch(self, context: FailureContext) -> Optional[dict]:
        """Produce a Fix dict, or ``None`` when no transform applies cleanly.

        Returns
        -------
        Fix dict with keys::

            patch           : str  unified diff (a/path …)
            confidence      : float in [0, 1]
            fix_type        : one of VALID_FIX_TYPES
            files_modified  : list[str]
            reasoning       : short explanation
            stage           : copied from analysis (or "unknown")
            risk_level      : "low" | "medium"
            root_cause      : same as reasoning (back-compat with ci_auto_fix)
            explanation     : same as reasoning (back-compat with ci_auto_fix)

        Returns ``None`` when:
          * no candidate transform matches the dispatch keys,
          * the candidate transform produces an empty / unsafe diff,
          * the resulting confidence is below ``self.min_confidence``,
          * the patch exceeds ``self.max_patched_lines`` changed lines,
          * the patch contains a placeholder (defensive — should never
            happen because every transform writes real content).
        """
        if not isinstance(context, FailureContext):
            return None
        if not context.files:
            return None

        candidates = self._dispatch(context)
        for candidate in candidates:
            fix = self._materialize(context, candidate)
            if fix is None:
                continue
            return fix
        return None

    # ── Dispatch ────────────────────────────────────────────────────────

    def _dispatch(self, ctx: FailureContext) -> list[dict]:
        """Return ordered list of transform descriptors to try.

        Each descriptor is a plain dict so the dispatch table stays
        introspectable for tests.
        """
        stage, reason = ctx.stage(), ctx.reason()
        out: list[dict] = []

        # Parser-shaped failures: planner produced unparseable JSON, or a
        # parse function is returning None and the caller forgot to guard.
        if (
            stage == "router" and reason == "invalid_plan_from_llm"
        ) or (
            stage == "planner" and reason in {"no_plan", "empty_plan"}
        ):
            out.append({
                "transform": "null_guard_after_assignment",
                "fix_type":  FIX_TYPE_PARSER,
                "confidence_base": 0.72,
                "reasoning": (
                    "Parser returned None; insert an explicit guard after "
                    "the assignment so the failure surfaces as a typed "
                    "error instead of a downstream NoneType crash."
                ),
            })

        # Executor-shaped failures: an exception escaped a step. Tighten
        # the catch to ``Exception`` so KeyboardInterrupt / SystemExit
        # propagate as the surrounding contract requires.
        if reason.startswith("unhandled_") or stage == "executor":
            out.append({
                "transform": "tighten_baseexception_to_exception",
                "fix_type":  FIX_TYPE_SAFETY,
                "confidence_base": 0.78,
                "reasoning": (
                    "BaseException catches swallow KeyboardInterrupt and "
                    "SystemExit. Narrowing to Exception preserves the "
                    "shutdown-signal contract while keeping ordinary error "
                    "isolation intact."
                ),
            })

        # Step-cap-overflow style: a max-iteration value is read from a
        # caller without an upper clamp. Insert min()/max() around the
        # int(...) coercion.
        if reason in {"executor_max_steps_overflow", "loop_max_iterations"}:
            out.append({
                "transform": "clamp_int_assignment",
                "fix_type":  FIX_TYPE_EXECUTOR,
                "confidence_base": 0.85,
                "reasoning": (
                    "An integer step/iteration count is consumed without "
                    "clamping. Wrapping the int(...) coercion in "
                    "min(HARD_MAX, max(1, int(...))) closes the unbounded-"
                    "input path without behavior change for valid inputs."
                ),
            })

        # Tool-not-found / tool-permission classes don't yield to a
        # surgical structural transform — the fix is usually a registry
        # update. Decline so the template fallback handles it.
        return out

    # ── Materializer ────────────────────────────────────────────────────

    def _materialize(
        self, ctx: FailureContext, candidate: dict,
    ) -> Optional[dict]:
        """Run one transform descriptor against the supplied files."""
        transform = candidate["transform"]
        runner = _TRANSFORMS.get(transform)
        if runner is None:
            return None

        # Walk the supplied files in deterministic order so test outputs
        # are stable regardless of dict iteration.
        for path in sorted(ctx.files.keys()):
            content = ctx.files[path]
            if not isinstance(content, str) or not content:
                continue
            try:
                result = runner(path, content, ctx)
            except Exception:
                # A transform crashing must never crash the whole
                # repair pipeline — silently move on.
                continue
            if result is None:
                continue
            new_content, hint = result
            if new_content == content:
                continue

            patch = _make_unified_diff(path, content, new_content)
            if not patch:
                continue
            if _PLACEHOLDER_RE.search(patch):
                # Transforms must NEVER emit placeholders. Defensive guard.
                continue
            changed = _count_changed_lines(patch)
            if changed == 0 or changed > self.max_patched_lines:
                continue

            confidence = float(candidate["confidence_base"])
            confidence = self._adjust_confidence(confidence, ctx, candidate)
            if confidence < self.min_confidence:
                continue

            reasoning = candidate["reasoning"]
            if hint:
                reasoning = f"{reasoning} ({hint})"

            return {
                "patch":          patch,
                "confidence":     round(confidence, 4),
                "fix_type":       candidate["fix_type"],
                "files_modified": [path],
                "reasoning":      reasoning,
                # Back-compat keys consumed by ci_auto_fix._finalise:
                "stage":          ctx.stage() or "unknown",
                "risk_level":     "low" if confidence >= 0.8 else "medium",
                "root_cause":     reasoning,
                "explanation":    reasoning,
                "lines_changed":  changed,
            }
        return None

    def _adjust_confidence(
        self, base: float, ctx: FailureContext, candidate: dict,
    ) -> float:
        """Lower confidence when prior history shows the same fix_type
        already failed for this signature. Pure read of ``recent_history``
        — no I/O."""
        if not ctx.recent_history:
            return base
        same_type_fails = sum(
            1 for h in ctx.recent_history
            if isinstance(h, dict)
            and h.get("fix_type") == candidate["fix_type"]
            and h.get("result") in {"failed", "flaky"}
        )
        # Each prior failure subtracts 0.10, capped at -0.30.
        penalty = min(0.30, 0.10 * same_type_fails)
        return max(0.0, base - penalty)


# ── Transforms ──────────────────────────────────────────────────────────────
#
# Each transform is `(path, content, ctx) -> Optional[(new_content, hint)]`.
# The hint is a short string appended to the reasoning when present.


def _t_tighten_baseexception(
    path: str, content: str, ctx: FailureContext,
) -> Optional[tuple[str, str]]:
    """Replace ``except BaseException`` with ``except Exception`` inside the
    function named in the traceback (or any function if no traceback hint)."""
    target_funcs = _functions_in_traceback(ctx.traceback, path)
    tree = _parse(content)
    if tree is None:
        return None

    # Find the target function nodes; if none mentioned, every function
    # in the file is a candidate (we'll still only edit lines that match).
    nodes = []
    if target_funcs:
        for fn in target_funcs:
            n = _find_function(tree, fn)
            if n is not None:
                nodes.append(n)
    if not nodes:
        nodes = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
    if not nodes:
        return None

    lines = content.splitlines(keepends=True)
    edits: list[tuple[int, str]] = []  # (line_index_zero_based, new_text)
    # Put longest alternative FIRST — `re` alternation is leftmost-match, so
    # `\s` would otherwise eat the space before `as e:` and drop the bind.
    pattern = re.compile(
        r"(\s*)except\s+BaseException(\s+as\s+\w+\s*:|\s*:|\s+(?=\())"
    )
    for node in nodes:
        start = node.lineno - 1  # 0-based
        end = (getattr(node, "end_lineno", None) or len(lines)) - 1
        for i in range(start, min(end + 1, len(lines))):
            m = pattern.match(lines[i])
            if m:
                indent = m.group(1)
                tail = m.group(2)
                # Keep any "as <name>:" tail intact.
                new = f"{indent}except Exception{tail}"
                # Preserve the line ending.
                eol = ""
                if lines[i].endswith("\r\n"):
                    eol = "\r\n"
                elif lines[i].endswith("\n"):
                    eol = "\n"
                if not new.endswith(eol):
                    new = new.rstrip("\r\n") + eol
                edits.append((i, new))

    if not edits:
        return None
    out_lines = list(lines)
    for i, txt in edits:
        out_lines[i] = txt
    return "".join(out_lines), f"replaced {len(edits)} BaseException catch(es)"


def _t_null_guard_after_assignment(
    path: str, content: str, ctx: FailureContext,
) -> Optional[tuple[str, str]]:
    """Find a variable that is assigned from a parser-style call and is
    then used unguarded; insert ``if X is None: raise ValueError(...)``
    immediately after the assignment.

    Heuristic: looks for ``<var> = parse_<something>(`` lines that are
    not already followed (within 3 lines) by an ``if <var> is None``
    guard. Conservative — only inserts where a clear gap exists.
    """
    tree = _parse(content)
    if tree is None:
        return None
    lines = content.splitlines(keepends=True)
    pattern = re.compile(
        r"^(\s*)(?P<var>[A-Za-z_]\w*)\s*=\s*(?:await\s+)?(?P<call>[A-Za-z_][\w.]*\()"
    )
    edits: list[tuple[int, str]] = []  # (insertion_line_index, text_to_insert)
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        call = m.group("call")
        # Only target functions whose name starts with parse_ / parse / load_
        if not re.match(r"^(parse_|parse\(|json\.|loads\()", call):
            continue
        var = m.group("var")
        indent = m.group(1)
        # Look at the next 3 non-blank lines for an existing guard.
        guard_already = False
        for j in range(i + 1, min(i + 4, len(lines))):
            stripped = lines[j].strip()
            if not stripped:
                continue
            if re.match(rf"if\s+{re.escape(var)}\s+is\s+None", stripped):
                guard_already = True
                break
            # Stop scanning if we leave the assignment's indentation.
            if not stripped.startswith("#") and (
                len(lines[j]) - len(lines[j].lstrip())
            ) < len(indent):
                break
        if guard_already:
            continue
        eol = "\n"
        if line.endswith("\r\n"):
            eol = "\r\n"
        guard = (
            f"{indent}if {var} is None:{eol}"
            f"{indent}    raise ValueError("
            f"\"repair_generator: {var} parse returned None\""
            f"){eol}"
        )
        edits.append((i + 1, guard))

    if not edits:
        return None
    # Insert from the bottom up so prior offsets stay valid.
    out_lines = list(lines)
    for i, text in sorted(edits, reverse=True):
        out_lines.insert(i, text)
    return "".join(out_lines), f"inserted null-guard for {len(edits)} parser call(s)"


def _t_clamp_int_assignment(
    path: str, content: str, ctx: FailureContext,
) -> Optional[tuple[str, str]]:
    """For lines that read ``X = int(<expr>)`` (or ``X = max(N, int(...))``),
    wrap with ``min(HARD_MAX, max(1, int(...)))`` if not already clamped.

    Conservative: only applies when:
      * the variable name contains 'step' or 'iteration' or 'max_'
        (case-insensitive),
      * the line does NOT already contain ``min(``.
    """
    lines = content.splitlines(keepends=True)
    pattern = re.compile(
        r"^(?P<indent>\s*)(?P<var>[A-Za-z_]\w*)\s*=\s*"
        r"(?P<rhs>(?:int|max)\([^\n]*?\))\s*(?P<comment>#[^\n]*)?$",
    )
    upper_bound = _detect_upper_bound(content)
    if upper_bound is None:
        upper_bound = 10  # matches HARD_MAX_STEPS in this repo

    edits: list[tuple[int, str]] = []
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        m = pattern.match(line)
        if not m:
            continue
        var = m.group("var").lower()
        if not any(tok in var for tok in ("step", "iter", "max_")):
            continue
        if "min(" in line:
            continue
        rhs = m.group("rhs")
        eol = "\r\n" if raw.endswith("\r\n") else ("\n" if raw.endswith("\n") else "")
        comment = m.group("comment")
        new_rhs = f"min({upper_bound}, max(1, {rhs}))"
        if comment:
            new_line = f"{m.group('indent')}{m.group('var')} = {new_rhs}  {comment}{eol}"
        else:
            new_line = f"{m.group('indent')}{m.group('var')} = {new_rhs}{eol}"
        edits.append((i, new_line))

    if not edits:
        return None
    out_lines = list(lines)
    for i, txt in edits:
        out_lines[i] = txt
    return (
        "".join(out_lines),
        f"clamped {len(edits)} int assignment(s) to [1, {upper_bound}]",
    )


_TRANSFORMS: dict[str, Any] = {
    "tighten_baseexception_to_exception": _t_tighten_baseexception,
    "null_guard_after_assignment":        _t_null_guard_after_assignment,
    "clamp_int_assignment":               _t_clamp_int_assignment,
}


# ── AST + diff helpers ──────────────────────────────────────────────────────


def _parse(content: str) -> Optional[ast.Module]:
    try:
        return ast.parse(content)
    except SyntaxError:
        return None


def _find_function(
    tree: ast.Module, name: str,
) -> Optional[ast.AST]:
    """Find a function or method by simple name or 'Class.method'."""
    if "." in name:
        cls, fn = name.split(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and item.name == fn:
                        return item
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    return None


_TB_FRAME_RE = re.compile(
    r'File\s+"(?P<path>[^"]+)",\s+line\s+\d+,\s+in\s+(?P<func>[A-Za-z_]\w*)'
)


def _functions_in_traceback(traceback: str, path_hint: str) -> list[str]:
    """Return function names mentioned in traceback frames whose file
    matches ``path_hint``. Most-recent (inner) frames first."""
    if not traceback:
        return []
    # Normalize path for comparison: traceback may use absolute or
    # relative paths. Match by basename equality OR substring.
    base = path_hint.rsplit("/", 1)[-1]
    found: list[str] = []
    for m in _TB_FRAME_RE.finditer(traceback):
        p = m.group("path")
        if base and (p.endswith(base) or path_hint in p):
            found.append(m.group("func"))
    # Inner frames are last in traceback text — reverse for innermost-first.
    return list(reversed(found))


def _detect_upper_bound(content: str) -> Optional[int]:
    """Look for ``HARD_MAX_STEPS = <int>`` (or similar) so the generated
    clamp uses the project's existing ceiling instead of inventing one."""
    m = re.search(
        r"^\s*(?:HARD_MAX_STEPS|HARD_MAX_ITERATIONS|MAX_STEPS|MAX_ITERATIONS)"
        r"\s*(?::\s*int)?\s*=\s*(\d+)",
        content,
        re.MULTILINE,
    )
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _make_unified_diff(path: str, before: str, after: str) -> str:
    """Emit a git-compatible unified diff. Empty string if no change."""
    if before == after:
        return ""
    diff_lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    out = "".join(diff_lines)
    # Ensure final newline so `git apply --check` is happy.
    if out and not out.endswith("\n"):
        out += "\n"
    return out


def _count_changed_lines(patch: str) -> int:
    """Count `+` and `-` body lines (excluding `+++ ` / `--- ` headers)."""
    if not patch:
        return 0
    n = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            n += 1
        elif line.startswith("-") and not line.startswith("---"):
            n += 1
    return n


__all__ = [
    "RepairGenerator",
    "FailureContext",
    # Fix-type vocabulary
    "FIX_TYPE_PARSER", "FIX_TYPE_EXECUTOR", "FIX_TYPE_TOOL",
    "FIX_TYPE_SAFETY", "FIX_TYPE_CI",
    "VALID_FIX_TYPES",
    # Tunables
    "MIN_GENERATOR_CONFIDENCE", "MAX_PATCHED_LINES",
]
