"""Policy evolution from outcome history — Phase G of the audit follow-up.

Reads the :class:`RepairOutcomeStore` ledger (now populated by Phase F's
GitHub feedback ingestor) and computes a *more-restrictive* dynamic
policy from observed reverter / regression rates. The dynamic layer
returns a new :class:`BrainPolicy` via :func:`dataclasses.replace` —
the static base from :mod:`infra.brain.policy` is never mutated.

The seven hard invariants from the Phase G spec are enforced in code,
not aspiration:

    1. **Restriction-only.** :meth:`PolicyEvolver.compute_dynamic_policy`
       intersects ``static.allowed_tools`` and
       ``static.allowed_capabilities`` with the keep-set computed from
       outcome history — never adds. A tool that's not in the static
       allowlist can never appear in the dynamic one.

    2. **Cold-start = base.** When ``len(matching_outcomes) <
       config.min_history`` for a tool, that tool is left alone. With
       zero history the entire dynamic policy equals the static one.

    3. **No mutation of policy.py constants.** The evolver only ever
       reads :data:`infra.brain.policy.NARAI_POLICY` /
       :data:`NAI_POLICY` (or any caller-supplied frozen
       :class:`BrainPolicy`) — it never writes back. Output is always a
       new frozen dataclass.

    4. **Kill switch is the cheapest path.** When ``config.enabled is
       False``, :meth:`compute_dynamic_policy` returns the input
       ``static`` policy unchanged before any I/O happens. Costs one
       boolean check.

    5. **Bounded rate of change.** A tool whose lifetime stats are bad
       can be re-allowed only when the most-recent
       ``config.stability_window`` outcomes show inverse stats. Below
       the window threshold, the tool stays restricted regardless of
       a recent good run — no flip-flopping.

    6. **Auditable.** Every restriction emits a
       ``policy_dynamic_restriction`` telemetry event with
       ``(tool_or_capability, kind, reason, evidence_count,
       success_rate, regression_rate)``. Use :meth:`explain` for the
       same data without applying anything.

    7. **No mutation of BrainPolicy.** :class:`BrainPolicy` stays
       ``frozen=True``. Output goes through ``dataclasses.replace``.

The decision rule is deterministic — no ML, no LLM, no scoring black
boxes. Heuristics over a JSONL log. Reproducible from the on-disk
ledger with ``cat`` / ``jq``.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Iterable, Optional

from ..policy import BrainPolicy
from .repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED,
)


_log = logging.getLogger("infra.brain.learning.policy_evolver")


# ── Telemetry ───────────────────────────────────────────────────────────


EVENT_POLICY_DYNAMIC_RESTRICTION: str = "policy_dynamic_restriction"
EVENT_POLICY_DYNAMIC_RESOLVED:    str = "policy_dynamic_resolved"


# ── Decision-rule outcome buckets ───────────────────────────────────────


# Outcomes that count toward "did we land this fix" success rate. An
# entry in ``applied`` is in-flight (no verdict yet) and is excluded
# from the denominator — we only count *terminated* outcomes so the
# rate doesn't move just because something is still being processed.
_TERMINAL_STATES: frozenset[str] = frozenset({
    STATE_MERGED, STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED, STATE_REGRESSED,
})
_SUCCESS_STATES: frozenset[str] = frozenset({STATE_MERGED})


# ── Config ──────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class EvolutionConfig:
    """Tunables for :class:`PolicyEvolver`.

    Defaults reflect the Phase G spec: ``enabled=False`` (the kill
    switch defaults to safe — Phase G ships disabled-by-default),
    ``min_history=20`` (cold-start carve-out), thresholds
    ``0.40`` / ``0.20`` for success / regression.

    All instances are frozen — config-by-mutation is a smell and we
    don't allow it.
    """

    enabled: bool = False
    min_history: int = 20
    restrict_below_success_rate: float = 0.40
    restrict_above_regression_rate: float = 0.20
    stability_window: int = 50


# ── Adjustment record (audit/explain output) ────────────────────────────


@dataclasses.dataclass(frozen=True)
class PolicyAdjustment:
    """One restriction the evolver would apply (or did apply).

    Returned in lists from :meth:`PolicyEvolver.explain`. Carries the
    exact evidence that justifies each restriction — the audit log
    line is a 1:1 reflection of what's stored in the JSONL ledger.

    Fields
    ------
    kind:
        ``"tool"`` or ``"capability"``.
    name:
        Tool name or capability token.
    reason:
        Short tag — one of ``"low_success_rate"``,
        ``"high_regression_rate"``, ``"all_tools_with_capability_restricted"``.
    success_rate:
        ``passed_terminal / total_terminal`` over the lifetime of
        outcomes touching the tool. ``0.0`` when no terminal
        outcomes exist (cold-start guard normally prevents this from
        reaching :class:`PolicyAdjustment`).
    regression_rate:
        ``count(regressed) / total_evidence``.
    evidence_count:
        Number of outcomes whose ``touched_tools`` includes this tool.
    """

    kind: str
    name: str
    reason: str
    success_rate: float
    regression_rate: float
    evidence_count: int


# ── Evolver ─────────────────────────────────────────────────────────────


class PolicyEvolver:
    """Compute dynamic restrictions on a static :class:`BrainPolicy`
    from outcome history.

    Stateless across calls — instantiate once per process or per call.
    All thresholds live on the :class:`EvolutionConfig` passed to each
    method, so different call sites can dial them without touching
    instance state.
    """

    # ── Public API ─────────────────────────────────────────────────

    def compute_dynamic_policy(
        self,
        static: BrainPolicy,
        store: RepairOutcomeStore,
        *,
        config: EvolutionConfig,
        tool_registry: Any = None,
    ) -> BrainPolicy:
        """Return a (possibly more restrictive) :class:`BrainPolicy`.

        When ``config.enabled is False``, returns ``static`` unchanged
        — fastest path, no I/O on the store. When the store is empty
        or every tool is below ``config.min_history``, also returns
        ``static`` unchanged.

        ``tool_registry`` is optional. When supplied, the evolver can
        also drop capabilities whose every member tool was restricted
        (per the Phase G spec). Without it, only tool-level
        restriction fires.
        """
        if not config.enabled:
            return static

        # Materialise the outcome list once. This is the only I/O.
        outcomes = list(store._iter_records())
        if not outcomes:
            return static

        # Compute the tool-level keep-set. Tools with insufficient
        # evidence pass through unchanged (cold-start invariant).
        adjustments = self._compute_adjustments(
            static, outcomes, config=config, tool_registry=tool_registry,
        )
        if not adjustments:
            return static

        # Project adjustments onto the static surface, never expanding it.
        new_allowed_tools = self._restrict_tools(
            static, adjustments,
        )
        new_allowed_capabilities = self._restrict_capabilities(
            static, adjustments,
        )

        # Emit one telemetry event per restriction. Auditability invariant.
        for adj in adjustments:
            _emit(
                EVENT_POLICY_DYNAMIC_RESTRICTION,
                kind=adj.kind,
                name=adj.name,
                reason=adj.reason,
                evidence_count=adj.evidence_count,
                success_rate=round(adj.success_rate, 4),
                regression_rate=round(adj.regression_rate, 4),
            )
        _emit(
            EVENT_POLICY_DYNAMIC_RESOLVED,
            mode=static.mode,
            restrictions=len(adjustments),
            tools_dropped=sum(1 for a in adjustments if a.kind == "tool"),
            capabilities_dropped=sum(
                1 for a in adjustments if a.kind == "capability"
            ),
        )

        return dataclasses.replace(
            static,
            allowed_tools=new_allowed_tools,
            allowed_capabilities=new_allowed_capabilities,
        )

    def explain(
        self,
        static: BrainPolicy,
        store: RepairOutcomeStore,
        *,
        config: EvolutionConfig,
        tool_registry: Any = None,
    ) -> list[PolicyAdjustment]:
        """Same logic as :meth:`compute_dynamic_policy`, but return the
        list of adjustments instead of applying them. Never emits
        telemetry — pure read for audit / debug surfaces.

        Honors ``config.enabled``: returns ``[]`` when off, so callers
        can use this as a "what would the evolver do if turned on?"
        probe without flipping the kill switch.
        """
        if not config.enabled:
            return []
        outcomes = list(store._iter_records())
        if not outcomes:
            return []
        return self._compute_adjustments(
            static, outcomes, config=config, tool_registry=tool_registry,
        )

    # ── Internals ──────────────────────────────────────────────────

    def _compute_adjustments(
        self,
        static: BrainPolicy,
        outcomes: list[RepairOutcome],
        *,
        config: EvolutionConfig,
        tool_registry: Any,
    ) -> list[PolicyAdjustment]:
        """Run the decision rule over the outcome list."""
        # Tools we can possibly restrict — only those in the static
        # allowlist. Restriction-only invariant: never expand beyond
        # the static surface.
        candidate_tools: tuple[str, ...] = static.allowed_tools or ()

        # Bucket outcomes by tool name. ``touched_tools=()`` outcomes
        # contribute to nothing here — that's the "outcome can't be
        # attributed to a tool" path, and we treat it as no evidence.
        per_tool: dict[str, list[RepairOutcome]] = {
            t: [] for t in candidate_tools
        }
        for outcome in outcomes:
            for tool in outcome.touched_tools or ():
                if tool in per_tool:
                    per_tool[tool].append(outcome)

        adjustments: list[PolicyAdjustment] = []
        restricted_tools: set[str] = set()

        for tool, tool_outcomes in per_tool.items():
            adjustment = self._tool_decision(
                tool=tool,
                outcomes=tool_outcomes,
                config=config,
            )
            if adjustment is not None:
                adjustments.append(adjustment)
                restricted_tools.add(tool)

        # Capability-level decisions need the tool registry to know
        # which capabilities each tool declares. Skip cleanly when no
        # registry is supplied.
        if tool_registry is not None and static.allowed_capabilities is not None:
            cap_adjustments = self._capability_decisions(
                static_caps=frozenset(static.allowed_capabilities),
                candidate_tools=candidate_tools,
                restricted_tools=restricted_tools,
                tool_registry=tool_registry,
            )
            adjustments.extend(cap_adjustments)

        return adjustments

    def _tool_decision(
        self,
        *,
        tool: str,
        outcomes: list[RepairOutcome],
        config: EvolutionConfig,
    ) -> Optional[PolicyAdjustment]:
        """Decide whether a single tool should be restricted.

        Cold-start invariant: returns ``None`` when
        ``len(outcomes) < config.min_history``. Stability window:
        a bad-lifetime tool is *not* restricted when its most-recent
        ``stability_window`` outcomes show inverse stats.
        """
        evidence_count = len(outcomes)
        if evidence_count < config.min_history:
            return None

        # Lifetime stats over all evidence for this tool.
        lifetime_success, lifetime_regression = _rates(outcomes)

        bad_lifetime = (
            lifetime_success < config.restrict_below_success_rate
            or lifetime_regression > config.restrict_above_regression_rate
        )
        if not bad_lifetime:
            return None

        # Re-allow check (bounded-rate-of-change invariant): the tool
        # is "improving" iff its most-recent run has at least
        # ``config.stability_window`` *consecutive* successful outcomes
        # since the last bad one (reverted / regressed /
        # rejected_by_review). In-flight ``applied`` outcomes don't
        # break the streak — they're not yet a verdict — but they
        # don't count toward the streak either.
        #
        # This is stricter than "look at last N outcomes; check stats"
        # because flip-flopping is exactly the failure mode a partial
        # window would hide. We want N solid wins, not N entries with
        # a passable aggregate.
        if config.stability_window > 0:
            consecutive_good = 0
            for o in reversed(outcomes):
                state = o.outcome_state
                if state == STATE_MERGED:
                    consecutive_good += 1
                elif state in {STATE_REVERTED, STATE_REGRESSED, STATE_REJECTED_BY_REVIEW}:
                    break
                # STATE_APPLIED is in-flight; doesn't count, doesn't
                # break the streak. Walking past it is fine because
                # the tool's verdicts are what matter for re-allow.
            if consecutive_good >= config.stability_window:
                return None

        reason = (
            "low_success_rate"
            if lifetime_success < config.restrict_below_success_rate
            else "high_regression_rate"
        )
        return PolicyAdjustment(
            kind="tool",
            name=tool,
            reason=reason,
            success_rate=lifetime_success,
            regression_rate=lifetime_regression,
            evidence_count=evidence_count,
        )

    def _capability_decisions(
        self,
        *,
        static_caps: frozenset[str],
        candidate_tools: Iterable[str],
        restricted_tools: set[str],
        tool_registry: Any,
    ) -> list[PolicyAdjustment]:
        """A capability is dropped iff every tool that declares it AND
        was in the static allowlist has been restricted.

        "Every" is load-bearing — a single non-restricted member tool
        keeps the capability. This satisfies the "drop only when ALL
        tools with capability X are restricted" rule from the spec.
        """
        # Build cap → set(tools-with-this-cap-from-static-allowlist).
        cap_to_tools: dict[str, set[str]] = {c: set() for c in static_caps}
        for name in candidate_tools:
            try:
                tool = tool_registry.get(name)
            except Exception:
                continue
            for cap in (tool.capabilities or ()):
                if cap in cap_to_tools:
                    cap_to_tools[cap].add(name)

        out: list[PolicyAdjustment] = []
        for cap, tools_having_it in cap_to_tools.items():
            if not tools_having_it:
                # No tool in the static allowlist declares this
                # capability. Don't drop it on emptiness alone — the
                # capability set is the safety baseline; future tool
                # registrations may need it.
                continue
            if tools_having_it.issubset(restricted_tools):
                out.append(PolicyAdjustment(
                    kind="capability",
                    name=cap,
                    reason="all_tools_with_capability_restricted",
                    success_rate=0.0,
                    regression_rate=0.0,
                    evidence_count=len(tools_having_it),
                ))
        return out

    @staticmethod
    def _restrict_tools(
        static: BrainPolicy, adjustments: list[PolicyAdjustment],
    ) -> Optional[tuple[str, ...]]:
        """Project tool-level restrictions onto ``static.allowed_tools``.

        ``static.allowed_tools is None`` means "unrestricted by name"
        on the static side. Restriction-only invariant: we cannot
        narrow ``None`` (= unrestricted) into a concrete subset
        without expanding the contract — the dynamic layer can only
        prune what's already there. So in the unrestricted-static
        case we leave ``allowed_tools`` as ``None`` and only act on
        capabilities.
        """
        if static.allowed_tools is None:
            return None
        dropped = {a.name for a in adjustments if a.kind == "tool"}
        if not dropped:
            return static.allowed_tools
        return tuple(t for t in static.allowed_tools if t not in dropped)

    @staticmethod
    def _restrict_capabilities(
        static: BrainPolicy, adjustments: list[PolicyAdjustment],
    ) -> Optional[frozenset[str]]:
        if static.allowed_capabilities is None:
            return None
        dropped = {a.name for a in adjustments if a.kind == "capability"}
        if not dropped:
            return static.allowed_capabilities
        return frozenset(
            c for c in static.allowed_capabilities if c not in dropped
        )


# ── Helpers ────────────────────────────────────────────────────────────


def _rates(
    outcomes: list[RepairOutcome],
) -> tuple[float, float]:
    """Return ``(success_rate, regression_rate)`` for an outcome list.

    success_rate    = merged / terminal-count (0.0 when no terminals)
    regression_rate = regressed / total-evidence (0.0 on empty)

    Definitions per the Phase G spec: success uses terminal denominator
    (so in-flight ``applied`` doesn't dilute), regression uses total
    denominator (because regression is a property of the population,
    not just the resolved subset).
    """
    if not outcomes:
        return 0.0, 0.0
    total = len(outcomes)
    terminal_count = 0
    success_count = 0
    regression_count = 0
    for o in outcomes:
        if o.outcome_state in _TERMINAL_STATES:
            terminal_count += 1
            if o.outcome_state in _SUCCESS_STATES:
                success_count += 1
            if o.outcome_state == STATE_REGRESSED:
                regression_count += 1
    success_rate = (success_count / terminal_count) if terminal_count else 0.0
    regression_rate = regression_count / total
    return success_rate, regression_rate


def _emit(event_type: str, **md: Any) -> None:
    """Forward a telemetry event to the active collector. No-op when
    none is bound — same pattern as the Phase D / E / F modules.

    The first param is named ``event_type`` so callers can pass
    ``kind=...`` metadata (which is already the convention for
    :class:`PolicyAdjustment` records) without colliding with the
    positional name. Compare to the analogous Phase F naming choice.
    """
    try:
        from ..telemetry import get_current_telemetry
    except Exception:  # pragma: no cover
        return
    col = get_current_telemetry()
    if col is None:
        return
    try:
        col.emit(event_type, **md)
    except Exception:  # pragma: no cover
        _log.debug("policy evolver telemetry emit failed", exc_info=True)


__all__ = [
    "EvolutionConfig",
    "PolicyAdjustment",
    "PolicyEvolver",
    "EVENT_POLICY_DYNAMIC_RESTRICTION",
    "EVENT_POLICY_DYNAMIC_RESOLVED",
]
