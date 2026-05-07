"""Self-improving CI repair memory.

A purely heuristic, deterministic, inspectable safety layer for the
autonomous CI repair pipeline. **No** ML, **no** external services,
**no** LLM reasoning — every decision is reproducible from the on-disk
JSONL log.

Storage
-------

Append-only JSONL at :data:`DEFAULT_MEMORY_PATH` (default
``.ci/repair-memory.jsonl``). Append-only is naturally crash-safe
(partial writes are dropped on the next read), inspectable from the
shell with ``cat`` / ``jq``, and trivially diff-able.

Schema (one JSON object per line)::

    {
      "test_id":            "infra/brain/tests/test_x.py::test_y",
      "failure_signature":  "abc123def456",
      "patch_diff":         "--- a/...\\n+++ b/...\\n@@ ...\\n",
      "applied":            true,
      "result":             "passed" | "failed" | "flaky",
      "stability_score":    0.0..1.0,
      "confidence_at_time": 0.0..1.0,
      "timestamp":          "2026-05-05T12:34:56+00:00"
    }

Decision rule (gate)
--------------------

::

    safe_score = success_rate
                 - flakiness_penalty
                 + repeated_success_bonus

If :func:`RepairMemory.should_block` returns ``True``, the patch must
not be applied. Cold-start (fewer than ``min_cases_for_gate`` similar
prior attempts) NEVER blocks — the memory simply has no opinion yet.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Tunables ────────────────────────────────────────────────────────────────


DEFAULT_THRESHOLD: float = 0.65
"""Below this score (when the gate is active), patches are blocked."""

MIN_CASES_FOR_GATE: int = 3
"""How many similar prior attempts are required before the gate kicks in."""

DEFAULT_MEMORY_PATH: str = ".ci/repair-memory.jsonl"
"""Default on-disk location for the JSONL log."""


VALID_RESULTS: frozenset[str] = frozenset({"passed", "failed", "flaky"})


# Failure categories — coarse buckets used for cross-signature similarity.
# Adding a new category here is a one-line change; the scoring code reads
# the field generically.
CATEGORY_PLANNER: str       = "planner_error"
CATEGORY_EXECUTOR_TOOL: str = "executor_tool_error"
CATEGORY_TELEMETRY: str     = "telemetry_failure"
CATEGORY_VALIDATION: str    = "validation_failure"
CATEGORY_UNKNOWN: str       = "unknown_runtime_error"

VALID_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_PLANNER, CATEGORY_EXECUTOR_TOOL, CATEGORY_TELEMETRY,
    CATEGORY_VALIDATION, CATEGORY_UNKNOWN,
})


# Fix patterns — coarse classification of WHAT the patch is trying to do.
# The classifier is keyword-based and deterministic; ambiguous patches get
# the catch-all ``unclassified_fix`` so the bucket they fall into doesn't
# silently dilute the others.
FIX_VALIDATION: str    = "validation_fix"
FIX_NULL_SAFETY: str   = "null_safety_fix"
FIX_TIMEOUT: str       = "timeout_fix"
FIX_PARSING: str       = "parsing_fix"
FIX_RETRY: str         = "retry_fix"
FIX_GUARDRAIL: str     = "guardrail_fix"
FIX_UNCLASSIFIED: str  = "unclassified_fix"

VALID_FIX_PATTERNS: frozenset[str] = frozenset({
    FIX_VALIDATION, FIX_NULL_SAFETY, FIX_TIMEOUT, FIX_PARSING,
    FIX_RETRY, FIX_GUARDRAIL, FIX_UNCLASSIFIED,
})


# ── Adaptive layer constants ───────────────────────────────────────────────
#
# Per-category prior on how risky a successful repair tends to be. Heavier
# values (closer to 1.0) push the gate harder; the unknown bucket gets the
# stiffest prior because by definition we don't have enough information.

RISK_PROFILES: dict[str, float] = {
    CATEGORY_PLANNER:       0.2,
    CATEGORY_EXECUTOR_TOOL: 0.5,
    CATEGORY_TELEMETRY:     0.1,
    CATEGORY_VALIDATION:    0.3,
    CATEGORY_UNKNOWN:       0.8,
}
DEFAULT_RISK_PENALTY: float = 0.4   # for any category not in the table


# Dynamic-threshold tuning. Reads only the last RECENT_WINDOW attempts.
RECENT_WINDOW: int       = 10
THRESHOLD_RAISE: float   = 0.15   # added when recent failures dominate
THRESHOLD_LOWER: float   = 0.10   # subtracted when recent fixes are stable
RECENT_FAIL_FLOOR: float = 0.50   # ≥ this fraction of failures → raise
RECENT_PASS_FLOOR: float = 0.10   # ≤ this fraction of failures → lower


# Anti-loop guard: a failure_signature seen LOOP_THRESHOLD times within the
# last LOOP_WINDOW attempts blocks the apply unconditionally — even at
# cold start. Loops are the one signal aggressive enough to override the
# cold-start carve-out.
LOOP_WINDOW: int       = 5
LOOP_THRESHOLD: int    = 3
LOOP_PENALTY: float    = 0.5   # applied to final_score when a loop is detected


# Fix-pattern reputation tunables.
REPUTATION_MIN_SAMPLES: int = 3      # below this, reputation is neutral
REPUTATION_HIGH_RATE: float = 0.8    # ≥ this → +bonus
REPUTATION_LOW_RATE: float  = 0.4    # ≤ this → -penalty
REPUTATION_BONUS: float     = 0.10
REPUTATION_PENALTY: float   = 0.20


_log = logging.getLogger("infra.brain.learning.repair_memory")


# ── Hashing / normalisation helpers ─────────────────────────────────────────


_PATH_RE     = re.compile(r"/[\w./-]+/(\w+\.py)")
_LINE_RE     = re.compile(r":\d+:")
_HEX_RE      = re.compile(r"0x[0-9a-fA-F]+")
_DIFF_HEAD   = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)


def _normalize_message(msg: str) -> str:
    """Strip path prefixes, line numbers, and hex addresses from an error
    message so signatures don't churn on every commit."""
    if not msg:
        return ""
    msg = _PATH_RE.sub(r"\1", msg)
    msg = _LINE_RE.sub(":L:", msg)
    msg = _HEX_RE.sub("0xADDR", msg)
    return msg.strip()[:200]


def compute_failure_signature(
    test_id: str,
    *,
    stage: str = "",
    reason: str = "",
    error_type: str = "",
    error_message: str = "",
) -> str:
    """Deterministic 16-hex-char hash that buckets equivalent failures.

    Two failures with the same ``(test_id, stage, reason, error_type,
    normalised error_message)`` produce the same signature — which is
    what we want for grouping repair history.
    """
    parts = (
        (test_id or "?").strip(),
        (stage or "?").strip(),
        (reason or "?").strip(),
        (error_type or "").strip(),
        _normalize_message(error_message or ""),
    )
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def normalize_patch(patch_diff: str) -> str:
    """Stable canonical form of a patch — strips line numbers in ``@@``
    headers and trailing whitespace so cosmetically-different patches that
    do the same thing hash to the same value."""
    if not patch_diff:
        return ""
    cleaned = _DIFF_HEAD.sub("@@ -X +Y @@", patch_diff)
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
    return cleaned.strip()


def patch_signature(patch_diff: str) -> str:
    """16-hex-char hash of the normalised patch."""
    return hashlib.sha256(normalize_patch(patch_diff).encode("utf-8")).hexdigest()[:16]


# ── Categorisation (deterministic, keyword-based) ───────────────────────────


def derive_failure_category(
    *,
    stage: str = "",
    reason: str = "",
    error_type: str = "",
) -> str:
    """Classify a failure into one of :data:`VALID_CATEGORIES`.

    Pure function over the strings the diagnostic stack already produces.
    Stable: equivalent (stage, reason, error_type) tuples always yield the
    same category, so the learning bucket is preserved across runs.
    """
    s = (stage or "").lower().strip()
    r = (reason or "").lower().strip()
    e = (error_type or "").lower().strip()

    if s == "planner" or "plan" in r:
        return CATEGORY_PLANNER
    if s == "telemetry" or "telemetry" in r or "event" in r:
        return CATEGORY_TELEMETRY
    if s in {"tool", "executor"} or "tool" in r or "step" in r:
        return CATEGORY_EXECUTOR_TOOL
    if (
        "valid" in r or "schema" in r or "invalid" in r
        or "valueerror" in e or "typeerror" in e
    ):
        return CATEGORY_VALIDATION
    return CATEGORY_UNKNOWN


# Keyword tables for fix-pattern classification. Order matters: most-specific
# patterns match first so a "validate + retry" patch lands in retry_fix only
# when the retry signal is dominant.
_FIX_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (FIX_TIMEOUT,     ("timeout", "deadline", "asyncio.wait_for", "time.sleep")),
    (FIX_RETRY,       ("retry", "retries=", "max_attempts", "backoff", "tenacity")),
    # NULL_SAFETY patterns are deliberately specific — overly-broad keywords
    # like "if not " caught isinstance() / has-attr checks too.
    (FIX_NULL_SAFETY, (" is none", " is not none", " or none",
                       " or {}", " or []", "getattr(", "is_none(",
                       "default=none")),
    (FIX_PARSING,     ("json.loads", "json.dumps", "parse_", "decode(",
                       ".strip()", ".split(", "re.match", "re.search")),
    (FIX_VALIDATION,  ("isinstance(", "raise valueerror", "raise typeerror",
                       "assert ", "validate", "schema")),
    (FIX_GUARDRAIL,   ("try:", "except ", "finally:", "with self.", "ensure",
                       "guard", "context manager")),
)


def classify_fix_pattern(patch_diff: str) -> str:
    """Heuristic classifier for the *intent* of a patch.

    Returns one of :data:`VALID_FIX_PATTERNS`. Looks ONLY at lines the
    patch *adds* (lines beginning with ``+``) — that's where the fix's
    intent lives. Lines beginning with ``-`` (removals) are deliberately
    ignored to keep the classifier from being fooled by surrounding
    context.
    """
    if not patch_diff:
        return FIX_UNCLASSIFIED
    added = "\n".join(
        line for line in patch_diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ).lower()
    if not added.strip():
        return FIX_UNCLASSIFIED
    for pattern, keywords in _FIX_KEYWORDS:
        for kw in keywords:
            if kw in added:
                return pattern
    return FIX_UNCLASSIFIED


# ── SafetyScore — the breakdown returned by compute_safety_score ──────────


@dataclass(frozen=True)
class SafetyScore:
    """Frozen breakdown of one safety-score computation.

    Attached to every patch-apply decision so the audit log says exactly
    why a patch was blocked or allowed.

    Fields
    ------
    score:
        The headline 0..1 number. Decision gate compares against threshold.
    success_rate:
        passed / total_applied. 0.0 when no prior applied attempts.
    flakiness:
        flaky / total_applied. 0.0 when no prior applied attempts.
        Distinct from ``risk_flags`` — those are categorical labels,
        this is the raw ratio used by the scoring formula.
    match_count:
        Total similar prior entries (signature OR category match).
    risk_flags:
        Human-readable categorical labels, e.g. ``flaky_history``,
        ``regression_seen``, ``no_prior_data``.
    """

    score: float
    success_rate: float
    flakiness: float
    match_count: int
    risk_flags: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "success_rate": self.success_rate,
            "flakiness": self.flakiness,
            "match_count": self.match_count,
            "risk_flags": list(self.risk_flags),
            # Back-compat alias retained so the previous turn's tests +
            # any external dashboards still resolve `similar_cases`.
            "similar_cases": self.match_count,
        }


# ── RepairMemory ───────────────────────────────────────────────────────────


class RepairMemory:
    """Append-only history of repair attempts + heuristic safety scorer.

    All operations are thread-safe (single re-entrant lock). The JSONL
    file is the source of truth; in-memory caches are invalidated on
    every write so concurrent writers don't drift.
    """

    REQUIRED_FIELDS: tuple[str, ...] = (
        "test_id",
        "failure_signature",
        "patch_diff",
        "applied",
        "result",
        "stability_score",
        "confidence_at_time",
        "timestamp",
    )

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        min_cases_for_gate: int = MIN_CASES_FOR_GATE,
    ) -> None:
        self.path = Path(path) if path else Path(DEFAULT_MEMORY_PATH)
        self.min_cases_for_gate = max(1, int(min_cases_for_gate))
        self._lock = threading.RLock()
        self._stats_cache: Optional[dict] = None

    # ── Recording ────────────────────────────────────────────────────────

    def record_attempt(self, entry: dict) -> None:
        """Append one repair-attempt record to the JSONL log.

        Validates that every required field is present + that ``result``
        is one of ``passed``, ``failed``, ``flaky``. Mutating the caller's
        dict is avoided (a shallow copy is taken).

        Optional fields ``failure_category`` and ``fix_pattern`` are
        auto-derived from ``patch_diff`` and the existing failure
        signals if the caller did not provide them — this keeps older
        callers (and old test fixtures) working without modification.
        """
        if not isinstance(entry, dict):
            raise TypeError(f"entry must be dict, got {type(entry).__name__}")
        missing = [f for f in self.REQUIRED_FIELDS if f not in entry]
        if missing:
            raise ValueError(f"missing required fields: {missing}")
        result = entry.get("result")
        if result not in VALID_RESULTS:
            raise ValueError(
                f"result must be one of {sorted(VALID_RESULTS)}; got {result!r}"
            )

        record = dict(entry)
        record.setdefault(
            "timestamp", datetime.now(timezone.utc).isoformat()
        )
        # Auto-derive optional fields if the caller didn't supply them.
        # Older fixtures (e.g. from the previous turn) record without
        # these — keep their behaviour intact while still populating the
        # categorisation columns for future scoring.
        if not record.get("failure_category"):
            record["failure_category"] = CATEGORY_UNKNOWN
        if not record.get("fix_pattern"):
            record["fix_pattern"] = classify_fix_pattern(
                str(record.get("patch_diff") or "")
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
            self._stats_cache = None  # invalidate
        # Persist a summary alongside the JSONL — fast reads for dashboards.
        try:
            self._write_summary()
        except Exception as e:  # pragma: no cover — diagnostic only
            _log.debug("could not write summary: %s", e)

    def update_statistics(self, entry: Optional[dict] = None) -> None:
        """Recompute aggregate statistics. Called after :meth:`record_attempt`
        to keep the on-disk summary fresh; safe to call independently."""
        with self._lock:
            self._stats_cache = None
        try:
            self._write_summary()
        except Exception as e:  # pragma: no cover
            _log.debug("could not write summary: %s", e)

    # ── Querying ─────────────────────────────────────────────────────────

    def query_similar_failures(
        self,
        failure_signature: str,
        *,
        failure_category: Optional[str] = None,
    ) -> list[dict]:
        """Return past entries similar to the given failure.

        Match rules (union — an entry matches if EITHER holds):

          1. Exact ``failure_signature`` match.
          2. When ``failure_category`` is given AND non-empty, entries
             whose recorded ``failure_category`` equals it. This widens
             the learning window across distinct test failures that
             share the same root cause (e.g., all planner errors learn
             from each other).

        Empty list if the log file does not exist yet (cold start).
        """
        if not failure_signature and not failure_category:
            return []
        if not self.path.exists():
            return []
        out: list[dict] = []
        seen_offsets: set[int] = set()
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                for offset, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        # Tolerate a partial-write at the file tail.
                        continue
                    sig_match = (
                        bool(failure_signature)
                        and rec.get("failure_signature") == failure_signature
                    )
                    cat_match = (
                        bool(failure_category)
                        and rec.get("failure_category") == failure_category
                    )
                    if (sig_match or cat_match) and offset not in seen_offsets:
                        seen_offsets.add(offset)
                        out.append(rec)
        return out

    def aggregate_stats(self) -> dict:
        """Return per-signature aggregates over the entire log.

        Cached in memory; invalidated on every write.
        """
        with self._lock:
            if self._stats_cache is not None:
                return self._stats_cache

        if not self.path.exists():
            stats = {"total_attempts": 0, "by_signature": {}}
            with self._lock:
                self._stats_cache = stats
            return stats

        by_sig: dict[str, dict[str, int]] = {}
        total = 0
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    total += 1
                    sig = rec.get("failure_signature") or "?"
                    bucket = by_sig.setdefault(sig, {
                        "applied": 0, "passed": 0, "failed": 0, "flaky": 0,
                    })
                    if rec.get("applied"):
                        bucket["applied"] += 1
                    res = rec.get("result")
                    if res in bucket:
                        bucket[res] += 1
        stats = {"total_attempts": total, "by_signature": by_sig}
        with self._lock:
            self._stats_cache = stats
        return stats

    def _write_summary(self) -> None:
        """Persist :meth:`aggregate_stats` next to the JSONL — useful for
        external dashboards that want the rollup without parsing every line."""
        stats = self.aggregate_stats()
        summary_path = self.path.with_suffix(".summary.json")
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(stats, indent=2, default=str, sort_keys=True)
        )

    # ── Scoring ──────────────────────────────────────────────────────────

    def compute_safety_score(
        self,
        failure_signature: str,
        patch_diff: str,
        *,
        failure_category: Optional[str] = None,
    ) -> dict:
        """Produce a safety-score breakdown for one prospective patch apply.

        Returns ``{"score", "success_rate", "flakiness", "match_count",
        "risk_flags", "similar_cases"}`` (the last is a back-compat alias).

        Heuristic::

            safe_score = success_rate
                         + repeated_success_bonus
                         - flakiness_penalty
                         - regression_penalty

        Where each component is bounded:

            success_rate          ∈ [0, 1]   passed / applied
            flakiness             ∈ [0, 1]   flaky / applied
            flakiness_penalty     ≤ 0.45     proportional to flakiness
            repeated_success_bonus≤ 0.20     for ≥ 3 clean passes
            regression_penalty    = 0.30     when same patch went pass→fail

        Cold-start (no prior data, or no prior *applied* attempts) returns
        ``score=1.0`` with a ``no_prior_data`` / ``never_applied`` risk
        flag. Combined with :meth:`should_block`'s
        ``match_count < min_cases_for_gate`` carve-out, this means a fresh
        system never auto-rejects patches purely for lack of history.

        Similarity widens via ``failure_category``: when given, entries
        sharing that category contribute to the learning bucket alongside
        exact signature matches.
        """
        similar = self.query_similar_failures(
            failure_signature, failure_category=failure_category,
        )
        risk_flags: list[str] = []

        if not similar:
            return SafetyScore(
                score=1.0, success_rate=0.0, flakiness=0.0, match_count=0,
                risk_flags=("no_prior_data",),
            ).to_dict()

        applied = [s for s in similar if s.get("applied") is True]
        if not applied:
            return SafetyScore(
                score=1.0, success_rate=0.0, flakiness=0.0,
                match_count=len(similar),
                risk_flags=("never_applied",),
            ).to_dict()

        passed = sum(1 for s in applied if s.get("result") == "passed")
        failed = sum(1 for s in applied if s.get("result") == "failed")
        flaky  = sum(1 for s in applied if s.get("result") == "flaky")
        total  = passed + failed + flaky
        success_rate = passed / total if total else 0.0
        flakiness    = flaky   / total if total else 0.0

        # ── Flakiness penalty (proportional, bounded) ────────────────────
        flakiness_penalty = 0.0
        if flaky > 0:
            flakiness_penalty = min(0.45, 0.15 + 0.05 * flaky)
            risk_flags.append("flaky_history")
        elif passed > 0 and failed > 0:
            flakiness_penalty = 0.15
            risk_flags.append("mixed_outcomes")

        # ── Repeated-success bonus ───────────────────────────────────────
        repeated_success_bonus = 0.0
        if passed >= 3 and failed == 0 and flaky == 0:
            repeated_success_bonus = min(0.20, 0.05 * passed)

        # ── Identical-patch-succeeded-before bonus ──────────────────────
        target_sig = patch_signature(patch_diff)
        if target_sig and any(
            patch_signature(s.get("patch_diff") or "") == target_sig
            and s.get("result") == "passed"
            for s in applied
        ):
            repeated_success_bonus = max(repeated_success_bonus, 0.15)
            risk_flags.append("identical_patch_succeeded_before")

        # ── Regression penalty: same patch went pass → fail ─────────────
        regression_penalty = 0.0
        if target_sig and _detect_regression(applied, target_sig):
            regression_penalty = 0.30
            risk_flags.append("regression_seen")

        score = (
            success_rate
            + repeated_success_bonus
            - flakiness_penalty
            - regression_penalty
        )
        score = max(0.0, min(1.0, score))

        return SafetyScore(
            score=score,
            success_rate=success_rate,
            flakiness=flakiness,
            match_count=len(similar),
            risk_flags=tuple(risk_flags),
        ).to_dict()

    # ── Decision helper ─────────────────────────────────────────────────

    def should_block(
        self,
        failure_signature: str,
        patch_diff: str,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        failure_category: Optional[str] = None,
    ) -> tuple[bool, dict]:
        """``(should_block, breakdown)``.

        Cold-start (``match_count < self.min_cases_for_gate``) NEVER
        blocks — the memory has no opinion until enough data has been
        collected. This is what makes the system backwards-compatible:
        a fresh repository with an empty JSONL behaves exactly like the
        pre-memory pipeline.

        ``failure_category`` widens the similarity match: when provided
        (and non-empty), entries from the same category contribute to
        the learning sample alongside exact signature matches.
        """
        breakdown = self.compute_safety_score(
            failure_signature, patch_diff,
            failure_category=failure_category,
        )
        if breakdown["match_count"] < self.min_cases_for_gate:
            return False, breakdown
        if breakdown["score"] < float(threshold):
            return True, breakdown
        return False, breakdown


    # ──────────────────────────────────────────────────────────────────
    # ADAPTIVE LAYER — extends the gate with dynamic threshold +
    # category risk + fix-pattern reputation + loop protection.
    # All methods here are pure reads over the JSONL log + the in-memory
    # cache. None of them mutate state.
    # ──────────────────────────────────────────────────────────────────

    def get_recent_attempts(self, n: int = RECENT_WINDOW) -> list[dict]:
        """Return the last ``n`` records, oldest-first.

        Pure read — uses the same partial-write tolerance as
        :meth:`query_similar_failures`.
        """
        if n < 1 or not self.path.exists():
            return []
        all_records: list[dict] = []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        all_records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return all_records[-n:]

    def compute_dynamic_threshold(
        self, *, base: float = DEFAULT_THRESHOLD,
    ) -> float:
        """Adjust the static threshold based on the last :data:`RECENT_WINDOW`
        attempts.

        Rules (per spec)::

            base + THRESHOLD_RAISE   if ≥ RECENT_FAIL_FLOOR fraction failed
            base - THRESHOLD_LOWER   if ≤ RECENT_PASS_FLOOR fraction failed
                                       AND we have ≥ 5 recent samples
            base                     otherwise
        """
        recent = self.get_recent_attempts(RECENT_WINDOW)
        if not recent:
            return float(base)
        n = len(recent)
        failures = sum(
            1 for r in recent if r.get("result") in {"failed", "flaky"}
        )
        fail_rate = failures / n
        if fail_rate >= RECENT_FAIL_FLOOR:
            return float(base) + THRESHOLD_RAISE
        if fail_rate <= RECENT_PASS_FLOOR and n >= 5:
            return float(base) - THRESHOLD_LOWER
        return float(base)

    def get_fix_reputation(self, fix_pattern: str) -> float:
        """Return the per-pattern reputation adjustment.

        Returns ``+REPUTATION_BONUS`` when the pattern's success_rate is
        ≥ :data:`REPUTATION_HIGH_RATE`, ``-REPUTATION_PENALTY`` when it's
        ≤ :data:`REPUTATION_LOW_RATE`, and ``0.0`` otherwise (including
        when there isn't enough data — :data:`REPUTATION_MIN_SAMPLES`).
        """
        if not fix_pattern:
            return 0.0
        stats = self._fix_pattern_stats().get(fix_pattern)
        if stats is None:
            return 0.0
        n = stats["success"] + stats["fail"]
        if n < REPUTATION_MIN_SAMPLES:
            return 0.0
        rate = stats["success"] / n
        if rate >= REPUTATION_HIGH_RATE:
            return REPUTATION_BONUS
        if rate <= REPUTATION_LOW_RATE:
            return -REPUTATION_PENALTY
        return 0.0

    def detect_loop(
        self,
        failure_signature: str,
        *,
        window: int = LOOP_WINDOW,
        threshold: int = LOOP_THRESHOLD,
    ) -> bool:
        """Return True when ``failure_signature`` appears at least
        ``threshold`` times in the last ``window`` attempts.

        Applied unconditionally — loops bypass the cold-start carve-out.
        """
        if not failure_signature:
            return False
        recent = self.get_recent_attempts(window)
        same_sig = sum(
            1 for r in recent if r.get("failure_signature") == failure_signature
        )
        return same_sig >= threshold

    def count_loop_preventions(self) -> int:
        """Reconstruct the historical loop-prevention count from the JSONL.

        For each ``applied=False`` record, walk back ``LOOP_WINDOW`` entries
        (inclusive of self) and count matching signatures; if that count
        crosses ``LOOP_THRESHOLD``, mark this entry as a loop prevention.
        Pure scan, no extra schema needed.
        """
        records = self.get_recent_attempts(10**9)  # all records
        records.sort(key=lambda r: str(r.get("timestamp") or ""))
        count = 0
        for i, rec in enumerate(records):
            if rec.get("applied"):
                continue
            sig = rec.get("failure_signature")
            if not sig:
                continue
            window = records[max(0, i - LOOP_WINDOW + 1):i + 1]
            if sum(1 for w in window if w.get("failure_signature") == sig) \
               >= LOOP_THRESHOLD:
                count += 1
        return count

    def compute_final_score(
        self,
        failure_signature: str,
        patch_diff: str,
        *,
        failure_category: Optional[str] = None,
        fix_pattern: Optional[str] = None,
        fix_confidence: Optional[float] = None,
    ) -> dict:
        """Compose the adaptive final score + every contributing component.

        Formula (per spec)::

            final_score = success_rate
                          + fix_reputation_bonus
                          - flakiness_penalty
                          - risk_profile_penalty
                          - loop_penalty

        clamped to [0, 1]. The ``base_safety_score`` from
        :meth:`compute_safety_score` is also returned so callers / dashboards
        can see what the pre-adaptive heuristic said.
        """
        base = self.compute_safety_score(
            failure_signature, patch_diff,
            failure_category=failure_category,
        )

        # Auto-classify the patch if the caller didn't supply a pattern.
        if not fix_pattern:
            fix_pattern = classify_fix_pattern(patch_diff)

        success_rate = float(base.get("success_rate") or 0.0)
        flakiness    = float(base.get("flakiness") or 0.0)

        # Flakiness penalty — proportional to flakiness ratio, capped 0.45
        # so the worst possible penalty is identical to the existing
        # `compute_safety_score` flakiness ceiling.
        flakiness_penalty = min(0.45, flakiness * 0.6)

        # Fix-pattern reputation: +0.1 / -0.2 / 0.0
        fix_reputation = self.get_fix_reputation(fix_pattern)

        # Per-category risk prior
        risk_profile_penalty = (
            RISK_PROFILES.get(failure_category, DEFAULT_RISK_PENALTY)
            if failure_category else DEFAULT_RISK_PENALTY
        )

        # Loop penalty / detection
        loop_detected = self.detect_loop(failure_signature)
        loop_penalty = LOOP_PENALTY if loop_detected else 0.0

        final_score = (
            success_rate
            + fix_reputation
            - flakiness_penalty
            - risk_profile_penalty
            - loop_penalty
        )
        final_score = max(0.0, min(1.0, final_score))

        # Recalibrated confidence — the planner's confidence weighted with
        # actual historical success. None when caller didn't supply one.
        final_confidence: Optional[float] = None
        if fix_confidence is not None:
            final_confidence = max(
                0.0, min(1.0, float(fix_confidence) * 0.5 + success_rate * 0.5)
            )

        threshold = self.compute_dynamic_threshold()

        return {
            "final_score":         round(final_score, 4),
            "threshold":           round(threshold, 4),
            "base_safety_score":   round(float(base.get("score") or 0.0), 4),
            "success_rate":        round(success_rate, 4),
            "flakiness":           round(flakiness, 4),
            "match_count":         int(base.get("match_count") or 0),
            "failure_category":    failure_category or "?",
            "fix_pattern":         fix_pattern or FIX_UNCLASSIFIED,
            "fix_reputation":      round(fix_reputation, 4),
            "risk_profile_penalty": round(risk_profile_penalty, 4),
            "loop_penalty":        round(loop_penalty, 4),
            "loop_detected":       loop_detected,
            "final_confidence":    (round(final_confidence, 4)
                                    if final_confidence is not None else None),
            "risk_flags":          list(base.get("risk_flags") or []),
            "similar_cases":       int(base.get("match_count") or 0),  # back-compat alias
        }

    def should_block_adaptive(
        self,
        failure_signature: str,
        patch_diff: str,
        *,
        failure_category: Optional[str] = None,
        fix_pattern: Optional[str] = None,
        fix_confidence: Optional[float] = None,
    ) -> tuple[bool, dict]:
        """Adaptive gate. Returns ``(should_block, breakdown)``.

        Decision order:

          1. Loop detected → BLOCK (overrides cold-start).
          2. ``match_count < min_cases_for_gate`` → ALLOW (cold start).
          3. ``final_score < threshold`` → BLOCK.
          4. Otherwise → ALLOW.
        """
        breakdown = self.compute_final_score(
            failure_signature, patch_diff,
            failure_category=failure_category,
            fix_pattern=fix_pattern,
            fix_confidence=fix_confidence,
        )

        if breakdown["loop_detected"]:
            return True, breakdown
        if breakdown["match_count"] < self.min_cases_for_gate:
            return False, breakdown
        if breakdown["final_score"] < breakdown["threshold"]:
            return True, breakdown
        return False, breakdown

    # ── System modes ─────────────────────────────────────────────────────
    #
    # The "mode" is a derived label over the dynamic threshold. It's the
    # operator-facing summary of how strict the gate is right now —
    # equivalent to inspecting compute_dynamic_threshold() directly but
    # easier to read in CI summaries.

    def current_mode(self) -> str:
        """Return ``"conservative"`` | ``"balanced"`` | ``"aggressive"`` based
        on where the dynamic threshold sits relative to the static base.
        """
        threshold = self.compute_dynamic_threshold()
        if threshold > DEFAULT_THRESHOLD + 0.05:
            return "conservative"
        if threshold < DEFAULT_THRESHOLD - 0.05:
            return "aggressive"
        return "balanced"

    # ── Observability summary ────────────────────────────────────────────

    def intelligence_summary(self) -> dict:
        """Compute the rolled-up summary used by
        :meth:`print_intelligence_summary`."""
        all_records = self.get_recent_attempts(10**9)
        total_attempts = len(all_records)
        successful = sum(
            1 for r in all_records
            if r.get("applied") and r.get("result") == "passed"
        )
        blocked = sum(1 for r in all_records if not r.get("applied"))
        loop_preventions = self.count_loop_preventions()

        # Top fix pattern (highest success_rate among patterns with ≥
        # REPUTATION_MIN_SAMPLES applies). Tie-break by sample size.
        fix_stats = self._fix_pattern_stats()
        top_fix_pattern = "?"
        best_score = -1.0
        for pat, st in fix_stats.items():
            n = st["success"] + st["fail"]
            if n < REPUTATION_MIN_SAMPLES:
                continue
            rate = st["success"] / n
            score = rate + (n / 1000.0)  # tiny boost for larger samples
            if score > best_score:
                best_score = score
                top_fix_pattern = pat

        # Worst failure type (most failed entries by category)
        cat_counts: dict[str, int] = {}
        for r in all_records:
            if r.get("result") in {"failed", "flaky"}:
                cat = r.get("failure_category") or CATEGORY_UNKNOWN
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        worst_failure_type = (
            max(cat_counts.items(), key=lambda kv: kv[1])[0]
            if cat_counts else "?"
        )

        return {
            "total_attempts":      total_attempts,
            "successful_repairs":  successful,
            "blocked_repairs":     blocked,
            "loop_preventions":    loop_preventions,
            "top_fix_pattern":     top_fix_pattern,
            "worst_failure_type":  worst_failure_type,
            "current_threshold":   round(self.compute_dynamic_threshold(), 4),
            "mode":                self.current_mode(),
        }

    def print_intelligence_summary(self, *, file=None) -> None:
        """Emit the [CI-INTELLIGENCE-SUMMARY] block in the spec format.

        Includes both the canonical field names (``total_attempts``,
        ``successful_repairs``, ``blocked_repairs``, ``loop_preventions``,
        ``top_fix_pattern``, ``worst_failure_type``, ``current_threshold``,
        ``mode``) AND the shorter aliases used by the most-recent spec
        (``attempts``, ``success``, ``blocked``, ``loops_prevented``,
        ``top_fix``, ``worst_failure``). All on separate lines so any
        log-grep that looks for a particular field finds it.
        """
        s = self.intelligence_summary()
        out = file if file is not None else __import__("sys").stdout
        print("[CI-INTELLIGENCE-SUMMARY]", file=out)
        print(f"total_attempts: {s['total_attempts']}", file=out)
        print(f"attempts: {s['total_attempts']}", file=out)
        print(f"successful_repairs: {s['successful_repairs']}", file=out)
        print(f"success: {s['successful_repairs']}", file=out)
        print(f"blocked_repairs: {s['blocked_repairs']}", file=out)
        print(f"blocked: {s['blocked_repairs']}", file=out)
        print(f"loop_preventions: {s['loop_preventions']}", file=out)
        print(f"loops_prevented: {s['loop_preventions']}", file=out)
        print(f"top_fix_pattern: {s['top_fix_pattern']}", file=out)
        print(f"top_fix: {s['top_fix_pattern']}", file=out)
        print(f"worst_failure_type: {s['worst_failure_type']}", file=out)
        print(f"worst_failure: {s['worst_failure_type']}", file=out)
        print(f"current_threshold: {s['current_threshold']}", file=out)
        print(f"mode: {s['mode']}", file=out, flush=True)

    # ── Internal: per-fix-pattern aggregation ────────────────────────────

    def _fix_pattern_stats(self) -> dict:
        """Per-fix-pattern aggregates over the entire log.
        ``{"validation_fix": {"success": int, "fail": int}, ...}``"""
        out: dict[str, dict[str, int]] = {}
        for rec in self.get_recent_attempts(10**9):
            if not rec.get("applied"):
                continue
            pat = rec.get("fix_pattern") or FIX_UNCLASSIFIED
            bucket = out.setdefault(pat, {"success": 0, "fail": 0})
            if rec.get("result") == "passed":
                bucket["success"] += 1
            else:
                bucket["fail"] += 1
        return out


def _detect_regression(applied_records: list[dict], target_patch_sig: str) -> bool:
    """True if a patch with the given signature went pass → fail in history.

    Walks the timestamp-ordered subset of records that share the patch
    signature and returns True the moment a "passed" outcome is followed
    by a "failed" outcome. A "flaky" outcome after a pass also counts as
    a regression — a flaky pass is, by definition, not a stable fix.
    """
    if not target_patch_sig:
        return False
    relevant = [
        r for r in applied_records
        if patch_signature(r.get("patch_diff") or "") == target_patch_sig
    ]
    if len(relevant) < 2:
        return False
    relevant.sort(key=lambda r: str(r.get("timestamp") or ""))
    seen_pass = False
    for r in relevant:
        result = r.get("result")
        if result == "passed":
            seen_pass = True
        elif result in {"failed", "flaky"} and seen_pass:
            return True
    return False


__all__ = [
    # Class + dataclass
    "RepairMemory",
    "SafetyScore",
    # Hash / normalization
    "compute_failure_signature",
    "normalize_patch",
    "patch_signature",
    # Categorisation
    "derive_failure_category",
    "classify_fix_pattern",
    # Constants
    "DEFAULT_THRESHOLD",
    "MIN_CASES_FOR_GATE",
    "DEFAULT_MEMORY_PATH",
    "VALID_RESULTS",
    "VALID_CATEGORIES",
    "VALID_FIX_PATTERNS",
    # Category constants
    "CATEGORY_PLANNER", "CATEGORY_EXECUTOR_TOOL",
    "CATEGORY_TELEMETRY", "CATEGORY_VALIDATION", "CATEGORY_UNKNOWN",
    # Fix-pattern constants
    "FIX_VALIDATION", "FIX_NULL_SAFETY", "FIX_TIMEOUT", "FIX_PARSING",
    "FIX_RETRY", "FIX_GUARDRAIL", "FIX_UNCLASSIFIED",
    # Adaptive layer
    "RISK_PROFILES", "DEFAULT_RISK_PENALTY",
    "RECENT_WINDOW", "THRESHOLD_RAISE", "THRESHOLD_LOWER",
    "RECENT_FAIL_FLOOR", "RECENT_PASS_FLOOR",
    "LOOP_WINDOW", "LOOP_THRESHOLD", "LOOP_PENALTY",
    "REPUTATION_MIN_SAMPLES", "REPUTATION_HIGH_RATE", "REPUTATION_LOW_RATE",
    "REPUTATION_BONUS", "REPUTATION_PENALTY",
]
