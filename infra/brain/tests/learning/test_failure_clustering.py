"""Phase E.2: tests for the failure clustering engine.

Coverage:

  * Identical signatures → one cluster (the cheap baseline signal).
  * Identical stack traces with different frame line numbers → one
    cluster (line-strip + shingle Jaccard works).
  * AST-skeleton-equal patches with renamed identifiers → one cluster
    (skeleton hash ignores names).
  * Token-level Levenshtein fallback when AST won't parse.
  * ``most_recurrent_clusters`` ordering correctness.
  * Threshold boundary cases: just-below threshold doesn't merge,
    just-at threshold does merge.
  * ``find_cluster`` returns None on a novel outcome with no peers.
  * Telemetry emit on compute + match.
  * dominant_fix_type and success_rate computed correctly when
    fetchers + terminal-state members are present.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from infra.brain.learning.failure_clustering import (
    DEFAULT_AST_PATTERN_THRESHOLD,
    DEFAULT_STACK_TRACE_THRESHOLD,
    EVENT_CLUSTER_COMPUTED,
    EVENT_CLUSTER_MATCH_FOUND,
    FailureCluster,
    FailureClusterer,
    _ast_skeleton_hash,
    _jaccard,
    _normalize_traceback,
    _normalized_levenshtein_similarity,
    _patch_tokens,
    _shingles,
    _stable_cluster_id,
)
from infra.brain.learning.repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _outcome(
    *,
    sig: str = "sig_default",
    patch: str = "patch_default",
    state: str = STATE_APPLIED,
    applied_at: str = "2026-05-05T22:00:00+00:00",
    observed_at: str = "2026-05-05T22:00:00+00:00",
    **extra,
) -> RepairOutcome:
    return RepairOutcome(
        failure_signature=sig,
        patch_hash=patch,
        applied_at=applied_at,
        outcome_state=state,
        outcome_observed_at=observed_at,
        **extra,
    )


# ── Pure-function helpers ──────────────────────────────────────────────


def test_normalize_traceback_strips_line_numbers():
    raw = 'File "x.py", line 42, in foo\n  raise RuntimeError("boom")'
    norm = _normalize_traceback(raw)
    assert "line 42" not in norm
    assert "line N" in norm


def test_jaccard_basic():
    assert _jaccard(frozenset(), frozenset()) == 0.0
    assert _jaccard(frozenset({"a"}), frozenset({"a"})) == 1.0
    assert _jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == pytest.approx(1 / 3)


def test_shingles_handles_short_input():
    assert _shingles("a b") == frozenset({"a b"})
    assert _shingles("") == frozenset()


def test_ast_skeleton_hash_collides_on_renames():
    """Same structure, different identifiers → same hash. Standard
    unified-diff format has no space between ``+`` and the content."""
    p1 = "+def foo(x):\n+    return x + 1\n"
    p2 = "+def bar(y):\n+    return y + 1\n"
    h1 = _ast_skeleton_hash(p1)
    h2 = _ast_skeleton_hash(p2)
    assert h1 is not None and h1 == h2


def test_ast_skeleton_hash_distinguishes_structures():
    p1 = "+def foo(x):\n+    return x + 1\n"
    p3 = "+def foo(x):\n+    for i in range(x):\n+        pass\n"
    h1 = _ast_skeleton_hash(p1)
    h3 = _ast_skeleton_hash(p3)
    assert h1 is not None and h3 is not None
    assert h1 != h3


def test_ast_skeleton_hash_returns_none_on_unparseable():
    assert _ast_skeleton_hash("+this is not valid python @@@\n") is None


def test_levenshtein_similarity_identity():
    toks = ["a", "b", "c"]
    assert _normalized_levenshtein_similarity(toks, list(toks)) == 1.0


def test_levenshtein_similarity_disjoint():
    a = ["a", "b", "c"]
    b = ["x", "y", "z"]
    sim = _normalized_levenshtein_similarity(a, b)
    assert 0.0 <= sim <= 0.34  # allow small float wiggle


def test_stable_cluster_id_is_order_independent():
    a = _stable_cluster_id(["p1", "p2", "p3"])
    b = _stable_cluster_id(["p3", "p1", "p2"])
    assert a == b
    assert len(a) == 16


# ── Signal 1: signature equality ────────────────────────────────────────


def test_identical_signatures_form_one_cluster():
    clusterer = FailureClusterer()
    outcomes = [
        _outcome(sig="s", patch="p1"),
        _outcome(sig="s", patch="p2"),
        _outcome(sig="s", patch="p3"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 1
    assert clusters[0].size == 3
    assert clusters[0].outcome_patch_hashes == ("p1", "p2", "p3")


def test_distinct_signatures_form_distinct_clusters_without_fetchers():
    """No fetchers → only signature-equality applies → one cluster per
    signature."""
    clusterer = FailureClusterer()
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
        _outcome(sig="s_c", patch="p3"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 3


# ── Signal 2: stack-trace shingle Jaccard ───────────────────────────────


def test_same_traceback_different_line_numbers_clusters():
    """Two distinct signatures + tracebacks that differ only in line
    numbers → cluster joined via shingle Jaccard."""
    tb_a = (
        'File "/repo/x.py", line 42, in run\n'
        '  raise RuntimeError("kaboom")\n'
        'RuntimeError: kaboom\n'
    )
    tb_b = (
        'File "/repo/x.py", line 137, in run\n'
        '  raise RuntimeError("kaboom")\n'
        'RuntimeError: kaboom\n'
    )
    tracebacks = {"p1": tb_a, "p2": tb_b}
    clusterer = FailureClusterer(
        traceback_fetcher=lambda o: tracebacks.get(o.patch_hash),
    )
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 1


def test_unrelated_tracebacks_stay_separate():
    tracebacks = {
        "p1": 'File "x.py", line 1, in foo\nValueError: bad input',
        "p2": 'File "y.py", line 2, in bar\nKeyError: missing',
    }
    clusterer = FailureClusterer(
        traceback_fetcher=lambda o: tracebacks.get(o.patch_hash),
    )
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 2


def test_threshold_boundary_for_stack_trace():
    """Tighten the threshold above what the test pair achieves;
    cluster splits. Loosen below; clusters merge."""
    tb_a = "File a.py line 1 RuntimeError x\nFile a.py line 2"
    tb_b = "File a.py line 1 RuntimeError x\nFile c.py line 9"
    tracebacks = {"p1": tb_a, "p2": tb_b}
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
    ]
    # Tight threshold (1.0) — will not merge unless tracebacks are identical.
    tight = FailureClusterer(
        stack_trace_threshold=1.0,
        traceback_fetcher=lambda o: tracebacks.get(o.patch_hash),
    )
    assert len(tight.cluster_all(outcomes)) == 2
    # Permissive threshold (0.0) — anything joins.
    loose = FailureClusterer(
        stack_trace_threshold=0.0,
        traceback_fetcher=lambda o: tracebacks.get(o.patch_hash),
    )
    # 0.0 plus our minimum-similarity hard floor → still merges
    # whenever there's any shingle overlap. These two share frames.
    assert len(loose.cluster_all(outcomes)) == 1


# ── Signal 3: AST skeleton + Levenshtein ───────────────────────────────


def test_ast_skeleton_equal_patches_with_renames_cluster():
    """Same structure, different variable names → cluster via AST hash."""
    p1 = "+def foo(x):\n+    return x + 1\n"
    p2 = "+def bar(y):\n+    return y + 1\n"
    diffs = {"p1": p1, "p2": p2}
    clusterer = FailureClusterer(
        patch_diff_fetcher=lambda o: diffs.get(o.patch_hash),
    )
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 1


def test_ast_pattern_threshold_boundary():
    """Disjoint token sequences with no AST overlap → no merge at the
    default threshold. Lower the threshold below the actual similarity
    → merge."""
    p1 = "+ x = 1\n+ y = 2\n"
    p2 = "+ totally different content here zzz\n"
    diffs = {"p1": p1, "p2": p2}
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
    ]
    # Tight threshold: doesn't merge.
    tight = FailureClusterer(
        ast_pattern_threshold=0.99,
        patch_diff_fetcher=lambda o: diffs.get(o.patch_hash),
    )
    assert len(tight.cluster_all(outcomes)) == 2
    # Permissive threshold: merges anything with non-empty token
    # sequences (Levenshtein normalised similarity is positive even
    # for very different sequences).
    loose = FailureClusterer(
        ast_pattern_threshold=0.0,
        patch_diff_fetcher=lambda o: diffs.get(o.patch_hash),
    )
    assert len(loose.cluster_all(outcomes)) == 1


def test_levenshtein_fallback_when_ast_unparseable():
    """Patches that don't parse as Python fall back to token-level
    Levenshtein. Identical token sequences → similarity 1.0 → merge."""
    p1 = "+ this isn't python @@@ but the tokens match\n"
    p2 = "+ this isn't python @@@ but the tokens match\n"
    diffs = {"p1": p1, "p2": p2}
    outcomes = [
        _outcome(sig="s_a", patch="p1"),
        _outcome(sig="s_b", patch="p2"),
    ]
    clusterer = FailureClusterer(
        patch_diff_fetcher=lambda o: diffs.get(o.patch_hash),
    )
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 1


# ── cluster_all output shape ───────────────────────────────────────────


def test_cluster_all_empty_input():
    clusters = FailureClusterer().cluster_all([])
    assert clusters == []


def test_cluster_id_is_deterministic():
    """Same outcomes in different order → same cluster_ids."""
    o1 = _outcome(sig="s", patch="p1")
    o2 = _outcome(sig="s", patch="p2")
    a = FailureClusterer().cluster_all([o1, o2])
    b = FailureClusterer().cluster_all([o2, o1])
    assert [c.cluster_id for c in a] == [c.cluster_id for c in b]


def test_cluster_canonical_signature_is_lex_smallest():
    """Clusters joined across signatures pick the lex-smallest
    signature as canonical — deterministic regardless of input order."""
    diffs = {"pA": "+ x = 1\n", "pB": "+ x = 1\n"}  # identical → AST-merge
    clusterer = FailureClusterer(
        patch_diff_fetcher=lambda o: diffs.get(o.patch_hash),
    )
    outcomes = [
        _outcome(sig="zzz_late", patch="pA"),
        _outcome(sig="aaa_early", patch="pB"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 1
    assert clusters[0].signature == "aaa_early"


# ── dominant_fix_type + success_rate ───────────────────────────────────


def test_dominant_fix_type_picks_majority():
    fixes = {"p1": "executor_fix", "p2": "executor_fix", "p3": "parser_fix"}
    clusterer = FailureClusterer(
        fix_type_fetcher=lambda o: fixes.get(o.patch_hash),
    )
    outcomes = [
        _outcome(sig="s", patch="p1"),
        _outcome(sig="s", patch="p2"),
        _outcome(sig="s", patch="p3"),
    ]
    clusters = clusterer.cluster_all(outcomes)
    assert len(clusters) == 1
    assert clusters[0].dominant_fix_type == "executor_fix"


def test_dominant_fix_type_none_without_fetcher():
    clusters = FailureClusterer().cluster_all([
        _outcome(sig="s", patch="p1"),
    ])
    assert clusters[0].dominant_fix_type is None


def test_success_rate_only_counts_terminal_members():
    outcomes = [
        _outcome(sig="s", patch="p1", state=STATE_MERGED),
        _outcome(sig="s", patch="p2", state=STATE_REVERTED),
        _outcome(sig="s", patch="p3", state=STATE_APPLIED),  # in-flight
    ]
    clusters = FailureClusterer().cluster_all(outcomes)
    assert len(clusters) == 1
    # 1 merged / 2 terminal (reverted + merged) = 0.5; applied excluded.
    assert clusters[0].success_rate == pytest.approx(0.5)


def test_success_rate_none_when_all_in_flight():
    outcomes = [
        _outcome(sig="s", patch="p1", state=STATE_APPLIED),
        _outcome(sig="s", patch="p2", state=STATE_APPLIED),
    ]
    clusters = FailureClusterer().cluster_all(outcomes)
    assert clusters[0].success_rate is None


def test_first_seen_last_seen_span():
    outcomes = [
        _outcome(sig="s", patch="p1", observed_at="2026-01-01T00:00:00+00:00"),
        _outcome(sig="s", patch="p2", observed_at="2026-05-05T00:00:00+00:00"),
    ]
    clusters = FailureClusterer().cluster_all(outcomes)
    assert clusters[0].first_seen.isoformat().startswith("2026-01-01")
    assert clusters[0].last_seen.isoformat().startswith("2026-05-05")


# ── find_cluster ───────────────────────────────────────────────────────


def test_find_cluster_returns_none_for_novel_outcome(tmp_path):
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    novel = _outcome(sig="never_seen", patch="brand_new")
    assert FailureClusterer().find_cluster(novel, store=store) is None


def test_find_cluster_locates_existing_signature_cluster(tmp_path):
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    store.record_outcome(_outcome(sig="hot", patch="p1"))
    store.record_outcome(_outcome(sig="hot", patch="p2"))
    target = _outcome(sig="hot", patch="p3")
    result = FailureClusterer().find_cluster(target, store=store)
    assert result is not None
    assert result.size == 3
    assert "p3" in result.outcome_patch_hashes


# ── most_recurrent_clusters ────────────────────────────────────────────


def test_most_recurrent_orders_by_size_descending(tmp_path):
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    # 1 outcome for sig_a, 3 for sig_b, 2 for sig_c
    store.record_outcome(_outcome(sig="sig_a", patch="a1"))
    for i in range(3):
        store.record_outcome(_outcome(sig="sig_b", patch=f"b{i}"))
    for i in range(2):
        store.record_outcome(_outcome(sig="sig_c", patch=f"c{i}"))
    out = FailureClusterer().most_recurrent_clusters(store, limit=10)
    sizes = [c.size for c in out]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[0] == 3  # sig_b cluster wins


def test_most_recurrent_respects_limit(tmp_path):
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    for i in range(5):
        store.record_outcome(_outcome(sig=f"s{i}", patch=f"p{i}"))
    out = FailureClusterer().most_recurrent_clusters(store, limit=2)
    assert len(out) == 2


def test_most_recurrent_zero_limit_returns_empty(tmp_path):
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    store.record_outcome(_outcome())
    assert FailureClusterer().most_recurrent_clusters(store, limit=0) == []


# ── Telemetry ──────────────────────────────────────────────────────────


def test_cluster_all_emits_computed_event():
    from infra.brain.telemetry.collector import _current_telemetry

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        FailureClusterer().cluster_all([
            _outcome(sig="s", patch="p1"),
            _outcome(sig="s", patch="p2"),
        ])
    finally:
        _current_telemetry.reset(token)

    computed = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_CLUSTER_COMPUTED
    ]
    assert len(computed) == 1
    assert computed[0].kwargs == {"count": 1, "outcomes": 2}


def test_find_cluster_emits_match_event_on_hit(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry

    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    store.record_outcome(_outcome(sig="hot", patch="p1"))

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        target = _outcome(sig="hot", patch="p2")
        FailureClusterer().find_cluster(target, store=store)
    finally:
        _current_telemetry.reset(token)

    matches = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_CLUSTER_MATCH_FOUND
    ]
    assert len(matches) == 1


# ── Robustness ─────────────────────────────────────────────────────────


def test_fetcher_exception_does_not_crash(caplog):
    """Fetcher raising → treated as missing data, clustering continues."""
    def boom(_o):
        raise RuntimeError("fetcher exploded")
    clusterer = FailureClusterer(traceback_fetcher=boom)
    clusters = clusterer.cluster_all([
        _outcome(sig="s", patch="p1"),
        _outcome(sig="s", patch="p2"),
    ])
    # Same-signature path still works; one cluster of 2.
    assert len(clusters) == 1
    assert clusters[0].size == 2
