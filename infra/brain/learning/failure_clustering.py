"""Failure clustering engine — Phase E.2 of the audit follow-up.

Groups :class:`infra.brain.learning.repair_outcome_memory.RepairOutcome`
records by structural similarity so the system can answer questions
like "this looks like 17 previous executor clamp bugs" without forcing
an LLM to scan every prior outcome.

Three similarity signals, combined via union-find:

  1. **Failure-signature equality** — exact match on the 16-hex-char
     hash from
     :func:`infra.brain.learning.repair_memory.compute_failure_signature`.
     Trivially cheap; the seed for cluster identity.

  2. **Stack-trace shingle Jaccard** — tokenize the traceback (frame
     paths + exception types), strip frame line numbers so a
     regression that moves to line N+5 still buckets with the original,
     generate ``k=3`` shingles, compute Jaccard. Default threshold
     ``stack_trace_threshold=0.65``.

  3. **Patch AST-pattern similarity** — for outcomes whose patches we
     have, parse the unified diff's added lines as Python, walk the
     AST, and hash the structural skeleton (node *types* only — no
     identifiers, no literals). Two patches cluster when their
     skeleton hashes match OR their normalized token sequences have
     Levenshtein-similarity ≥ ``ast_pattern_threshold=0.80``.

Only the first signal can be derived from a :class:`RepairOutcome`
alone; the other two need the original traceback / patch_diff text,
which the outcome ledger deliberately doesn't store (keys-only).
The :class:`FailureClusterer` accepts optional fetcher callables —
when supplied, the deeper signals fire; when not, clustering degrades
to signature-equality only and the engine still produces valid
clusters (just coarser).

Phase E ships the engine ONLY. Wiring into ``attempt_repair()`` /
``RepairGenerator`` / policy evolution is queued for Phase F/G.

Boundary: lives under ``infra/brain/learning/``. Not re-exported from
:mod:`infra.brain.interface` — the CI grep guard at
``.github/workflows/brain-tests.yml`` enforces external boundaries;
internal imports inside ``infra/brain/`` are free to use this module.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from .repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED,
)


_log = logging.getLogger("infra.brain.learning.failure_clustering")


# ── Tunables ────────────────────────────────────────────────────────────


DEFAULT_STACK_TRACE_THRESHOLD: float = 0.65
DEFAULT_AST_PATTERN_THRESHOLD: float = 0.80
DEFAULT_SHINGLE_K: int = 3


# Telemetry events — bare strings (per ``events.py`` "any custom string
# for plug-in events" allowance).
EVENT_CLUSTER_COMPUTED:    str = "failure_cluster_computed"
EVENT_CLUSTER_MATCH_FOUND: str = "failure_cluster_match_found"


# Type aliases for the optional fetchers.
TracebackFetcher = Callable[[RepairOutcome], Optional[str]]
PatchDiffFetcher = Callable[[RepairOutcome], Optional[str]]
FixTypeFetcher   = Callable[[RepairOutcome], Optional[str]]


# Outcome states that count toward "success rate" as the cluster's
# resolution metric. ``applied`` is in-flight (not yet a verdict).
_TERMINAL_STATES: frozenset[str] = frozenset({
    STATE_MERGED, STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED, STATE_REGRESSED,
})
_SUCCESS_STATES: frozenset[str] = frozenset({STATE_MERGED})


# ── FailureCluster dataclass ────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class FailureCluster:
    """One similarity-grouped collection of outcomes.

    Fields
    ------
    cluster_id:
        Stable 16-hex-char hash of the *sorted* patch_hashes. Two
        clusterer runs over the same outcomes always produce the same
        ``cluster_id``.
    signature:
        Canonical signature for the cluster. When all members share a
        ``failure_signature`` (most common case) this is that
        signature; when the cluster spans multiple signatures (joined
        via stack-trace or AST similarity) it is the lexicographically
        smallest member signature, so the choice is deterministic and
        not arrival-order-dependent.
    outcome_patch_hashes:
        Sorted tuple of every patch_hash in the cluster. Sorted so
        equality of clusters is structural, not order-dependent.
    size:
        ``len(outcome_patch_hashes)`` — convenience.
    first_seen / last_seen:
        Min and max ``outcome_observed_at`` across cluster members,
        parsed as UTC datetime.
    dominant_fix_type:
        Most common fix_type across cluster members, when a
        ``fix_type_fetcher`` is provided. ``None`` otherwise.
    success_rate:
        Fraction of cluster members in a successful terminal state
        (``merged``) over the count of members in any terminal state
        (``merged + reverted + regressed + rejected_by_review``).
        ``None`` when no member has reached a terminal state yet.
    """

    cluster_id: str
    signature: str
    outcome_patch_hashes: tuple[str, ...]
    size: int
    first_seen: datetime
    last_seen: datetime
    dominant_fix_type: Optional[str] = None
    success_rate: Optional[float] = None


# ── Internal helpers ────────────────────────────────────────────────────


_TB_LINE_NO_RE = re.compile(r"line\s+\d+")


def _normalize_traceback(tb: str) -> str:
    """Strip frame line numbers so the same crash at a different line
    still buckets together."""
    if not tb:
        return ""
    return _TB_LINE_NO_RE.sub("line N", tb)


def _tokenize(text: str) -> list[str]:
    """Identifier-style tokenization — alphanumeric + underscore + dot
    + slash to keep file paths and dotted exception types intact."""
    return re.findall(r"[A-Za-z_][A-Za-z0-9_./]*", text)


def _shingles(text: str, k: int = DEFAULT_SHINGLE_K) -> frozenset[str]:
    """k-shingle set over identifier tokens. ``k=3`` by default."""
    tokens = _tokenize(text)
    if len(tokens) < k:
        return frozenset({" ".join(tokens)} if tokens else set())
    return frozenset(
        " ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)
    )


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _added_lines(patch_diff: str) -> str:
    """Concatenate the ``+`` body lines of a unified diff."""
    if not patch_diff:
        return ""
    return "\n".join(
        line[1:] for line in patch_diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _ast_skeleton_hash(patch_diff: str) -> Optional[str]:
    """Hash the structural skeleton of a patch's added lines.

    Walks the AST and emits ``type(node).__name__`` per node. Identifiers
    and literal values are *not* included, so two patches that differ
    only in variable names produce the same hash. Returns ``None`` when
    the added lines don't parse as Python (best-effort — partial
    function-body snippets may not be parseable on their own).
    """
    src = _added_lines(patch_diff)
    if not src:
        return None
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    types = [type(node).__name__ for node in ast.walk(tree)]
    if not types:
        return None
    return hashlib.sha256("|".join(types).encode("utf-8")).hexdigest()[:16]


def _patch_tokens(patch_diff: str) -> list[str]:
    """Token sequence from a patch's added lines, used for Levenshtein
    fallback when the AST skeleton can't be computed."""
    src = _added_lines(patch_diff)
    if not src:
        return []
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\S", src)


def _levenshtein(a: list[str], b: list[str]) -> int:
    """Token-level edit distance. O(m * n)."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(
                prev[j] + 1,        # delete
                cur[j - 1] + 1,     # insert
                prev[j - 1] + cost,  # substitute
            )
        prev = cur
    return prev[n]


def _normalized_levenshtein_similarity(
    a: list[str], b: list[str],
) -> float:
    """``1 - levenshtein/max(len)``. Returns ``1.0`` for two empty
    sequences."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / max_len


def _parse_iso(s: str) -> datetime:
    """Parse the ISO 8601 timestamps the rest of the brain uses.
    Naive datetimes are normalised to UTC."""
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stable_cluster_id(patch_hashes: Iterable[str]) -> str:
    """Deterministic 16-hex hash of the sorted patch_hash tuple."""
    canon = "|".join(sorted(patch_hashes))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


# ── Union-find ─────────────────────────────────────────────────────────


class _UnionFind:
    """Path-compressed disjoint-set forest, dict-backed."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> list[list[str]]:
        out: dict[str, list[str]] = {}
        for x in self._parent:
            root = self.find(x)
            out.setdefault(root, []).append(x)
        return list(out.values())


# ── Public API ──────────────────────────────────────────────────────────


class FailureClusterer:
    """Group repair outcomes by structural similarity.

    Stateless across calls — instantiate once per process or per call.
    Thresholds and fetchers are constructor args so individual call
    sites can dial them without monkey-patching.

    Telemetry: emits ``failure_cluster_computed`` after each
    :meth:`cluster_all` invocation and ``failure_cluster_match_found``
    inside :meth:`find_cluster` when a match is located. Both events
    are best-effort — they go through the ContextVar-bound collector
    if one is active, no-op otherwise.
    """

    def __init__(
        self,
        *,
        stack_trace_threshold: float = DEFAULT_STACK_TRACE_THRESHOLD,
        ast_pattern_threshold: float = DEFAULT_AST_PATTERN_THRESHOLD,
        shingle_k: int = DEFAULT_SHINGLE_K,
        traceback_fetcher: Optional[TracebackFetcher] = None,
        patch_diff_fetcher: Optional[PatchDiffFetcher] = None,
        fix_type_fetcher: Optional[FixTypeFetcher] = None,
    ) -> None:
        self.stack_trace_threshold = float(stack_trace_threshold)
        self.ast_pattern_threshold = float(ast_pattern_threshold)
        self.shingle_k = max(1, int(shingle_k))
        self._traceback_fetcher = traceback_fetcher
        self._patch_diff_fetcher = patch_diff_fetcher
        self._fix_type_fetcher = fix_type_fetcher

    # ── cluster_all ────────────────────────────────────────────────

    def cluster_all(
        self, outcomes: Iterable[RepairOutcome],
    ) -> list[FailureCluster]:
        """Pure function: take a finite iterable of outcomes, return
        the list of :class:`FailureCluster` objects covering them.

        No I/O. Telemetry emit at the end is the only side effect, and
        is itself a no-op when no collector is bound.
        """
        outcomes_list = list(outcomes)
        if not outcomes_list:
            self._emit(EVENT_CLUSTER_COMPUTED, count=0, outcomes=0)
            return []

        # Cache fetcher results once per outcome — these can be
        # expensive (file reads, API calls) and we use them across
        # O(N²) pair comparisons below.
        tracebacks: dict[str, str] = {}
        patch_diffs: dict[str, str] = {}
        ast_hashes:  dict[str, Optional[str]] = {}
        patch_toks:  dict[str, list[str]] = {}
        shingle_sets: dict[str, frozenset[str]] = {}
        fix_types:   dict[str, Optional[str]] = {}

        for o in outcomes_list:
            ph = o.patch_hash
            tb = self._fetch(self._traceback_fetcher, o)
            pd = self._fetch(self._patch_diff_fetcher, o)
            ft = self._fetch(self._fix_type_fetcher, o)
            tracebacks[ph] = tb or ""
            patch_diffs[ph] = pd or ""
            ast_hashes[ph] = _ast_skeleton_hash(pd or "")
            patch_toks[ph] = _patch_tokens(pd or "")
            shingle_sets[ph] = _shingles(
                _normalize_traceback(tb or ""), self.shingle_k,
            )
            fix_types[ph] = ft

        # Union-find seeded with every patch_hash.
        uf = _UnionFind()
        for o in outcomes_list:
            uf.add(o.patch_hash)

        # Pairwise pass — cheap signal first, expensive last.
        n = len(outcomes_list)
        for i in range(n):
            a = outcomes_list[i]
            ph_a = a.patch_hash
            for j in range(i + 1, n):
                b = outcomes_list[j]
                ph_b = b.patch_hash
                if uf.find(ph_a) == uf.find(ph_b):
                    continue  # already in same cluster

                # Signal 1: signature equality (cheapest).
                if a.failure_signature == b.failure_signature:
                    uf.union(ph_a, ph_b)
                    continue

                # Signal 2: stack-trace Jaccard.
                if shingle_sets[ph_a] and shingle_sets[ph_b]:
                    sim = _jaccard(shingle_sets[ph_a], shingle_sets[ph_b])
                    if sim >= self.stack_trace_threshold:
                        uf.union(ph_a, ph_b)
                        continue

                # Signal 3: AST-skeleton hash equality, then Levenshtein
                # fallback on tokens.
                ha, hb = ast_hashes[ph_a], ast_hashes[ph_b]
                if ha is not None and ha == hb:
                    uf.union(ph_a, ph_b)
                    continue
                ta, tb_tok = patch_toks[ph_a], patch_toks[ph_b]
                if ta and tb_tok:
                    sim = _normalized_levenshtein_similarity(ta, tb_tok)
                    if sim >= self.ast_pattern_threshold:
                        uf.union(ph_a, ph_b)

        # Materialise clusters.
        outcomes_by_hash = {o.patch_hash: o for o in outcomes_list}
        clusters: list[FailureCluster] = []
        for group in uf.groups():
            members = [outcomes_by_hash[h] for h in group]
            clusters.append(self._build_cluster(members, fix_types))

        # Determinism: sort by cluster_id so two runs over the same
        # input produce the same output ordering.
        clusters.sort(key=lambda c: c.cluster_id)
        self._emit(
            EVENT_CLUSTER_COMPUTED,
            count=len(clusters),
            outcomes=len(outcomes_list),
        )
        return clusters

    def _build_cluster(
        self,
        members: list[RepairOutcome],
        fix_types: dict[str, Optional[str]],
    ) -> FailureCluster:
        patch_hashes = tuple(sorted(m.patch_hash for m in members))
        timestamps = [_parse_iso(m.outcome_observed_at) for m in members]
        first_seen = min(timestamps)
        last_seen = max(timestamps)

        # Canonical signature: lex-smallest unique signature in the
        # cluster. Deterministic regardless of input order.
        sigs = sorted({m.failure_signature for m in members})
        signature = sigs[0] if sigs else ""

        # Dominant fix_type: most common non-None value.
        ft_counts: dict[str, int] = {}
        for m in members:
            ft = fix_types.get(m.patch_hash)
            if ft:
                ft_counts[ft] = ft_counts.get(ft, 0) + 1
        dominant_fix_type: Optional[str] = None
        if ft_counts:
            dominant_fix_type = max(
                ft_counts.items(), key=lambda kv: (kv[1], kv[0]),
            )[0]

        # Success rate: merged / (merged + reverted + regressed + rejected_by_review).
        terminal = [m for m in members if m.outcome_state in _TERMINAL_STATES]
        success_rate: Optional[float] = None
        if terminal:
            successes = sum(
                1 for m in terminal if m.outcome_state in _SUCCESS_STATES
            )
            success_rate = successes / len(terminal)

        return FailureCluster(
            cluster_id=_stable_cluster_id(patch_hashes),
            signature=signature,
            outcome_patch_hashes=patch_hashes,
            size=len(patch_hashes),
            first_seen=first_seen,
            last_seen=last_seen,
            dominant_fix_type=dominant_fix_type,
            success_rate=success_rate,
        )

    # ── find_cluster ──────────────────────────────────────────────

    def find_cluster(
        self,
        outcome: RepairOutcome,
        *,
        store: RepairOutcomeStore,
    ) -> Optional[FailureCluster]:
        """Locate the cluster that ``outcome`` belongs to among the
        store's history. Returns ``None`` when no other outcome in the
        store is similar enough.

        Strategy: pull candidates by signature first (cheapest narrow);
        if the signature is novel and we have a traceback, fall back
        to scanning the full store and clustering the union.
        """
        # Cheap narrow: same-signature candidates already cluster.
        candidates = store.query_by_signature(
            outcome.failure_signature, limit=200,
        )
        # Make sure the input outcome is always in the candidate set.
        if outcome.patch_hash not in {c.patch_hash for c in candidates}:
            candidates = [outcome] + candidates

        if len(candidates) > 1:
            clusters = self.cluster_all(candidates)
            for c in clusters:
                if outcome.patch_hash in c.outcome_patch_hashes:
                    self._emit(
                        EVENT_CLUSTER_MATCH_FOUND,
                        cluster_id=c.cluster_id,
                        cluster_size=c.size,
                        signature=c.signature,
                    )
                    return c

        # Single-member cluster doesn't count as a "match" — caller
        # wants similar prior history, not just the outcome itself.
        return None

    # ── most_recurrent_clusters ───────────────────────────────────

    def most_recurrent_clusters(
        self,
        store: RepairOutcomeStore,
        *,
        limit: int = 10,
        scan_limit: int = 1000,
    ) -> list[FailureCluster]:
        """Return up to ``limit`` clusters from the store, sorted by
        size (most-recurrent first), tie-broken by ``last_seen``
        descending.

        ``scan_limit`` caps how many recent outcomes the engine pulls
        per signature before clustering — protects against pathological
        ledgers without surfacing the limit in the public arg list.
        """
        if limit < 1:
            return []

        # Pull a wide enough sample to be representative without
        # forcing a full-history scan. We don't have a "list all
        # signatures" API on the store today — Phase F may add one —
        # so this method works against the JSONL via _iter_records.
        seen_sigs: set[str] = set()
        all_outcomes: list[RepairOutcome] = []
        for entry in store._iter_records():  # internal — same crate
            seen_sigs.add(entry.failure_signature)
            all_outcomes.append(entry)
            if len(all_outcomes) >= scan_limit:
                break

        if not all_outcomes:
            return []

        # Latest-state-per-patch (collapse lifecycle entries) so the
        # cluster's success_rate reflects the most recent verdict.
        latest_per: dict[str, RepairOutcome] = {}
        for o in all_outcomes:
            latest_per[o.patch_hash] = o

        clusters = self.cluster_all(latest_per.values())
        clusters.sort(
            key=lambda c: (-c.size, -c.last_seen.timestamp(), c.cluster_id),
        )
        return clusters[:limit]

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _fetch(
        fetcher: Optional[Callable[[RepairOutcome], Optional[str]]],
        outcome: RepairOutcome,
    ) -> Optional[str]:
        if fetcher is None:
            return None
        try:
            return fetcher(outcome)
        except Exception:
            _log.debug(
                "fetcher raised for %s; treating as missing data",
                outcome.patch_hash, exc_info=True,
            )
            return None

    @staticmethod
    def _emit(event_type: str, **md) -> None:
        try:
            from ..telemetry import get_current_telemetry
        except Exception:
            return
        col = get_current_telemetry()
        if col is None:
            return
        try:
            col.emit(event_type, **md)
        except Exception:  # pragma: no cover
            pass


__all__ = [
    # Class + dataclass
    "FailureClusterer",
    "FailureCluster",
    # Tunables
    "DEFAULT_STACK_TRACE_THRESHOLD",
    "DEFAULT_AST_PATTERN_THRESHOLD",
    "DEFAULT_SHINGLE_K",
    # Telemetry
    "EVENT_CLUSTER_COMPUTED",
    "EVENT_CLUSTER_MATCH_FOUND",
    # Type aliases
    "TracebackFetcher",
    "PatchDiffFetcher",
    "FixTypeFetcher",
]
