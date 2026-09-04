"""§24 approval conversation — a natural approval TURN over the EXISTING approval model.

This is NOT a second approval store, policy, or queue. It is the conversational layer that:
  1. presents a consequential pending action as the inline §24/§60 package
     (ACTION / TARGET / ENVIRONMENT / RISK / EVIDENCE / ROLLBACK / EXACT-AUTHORITY-REQUESTED),
     reusing the self_improvement.owner_review_package / command_router._approval_package shape; and
  2. interprets the owner's reply, and — ONLY on an explicit, unambiguous confirmation bound to a
     specific pending action id — resolves it to a DURABLE approval record via the EXISTING
     proposals_store.decide (never a chat string, never in-memory truth).

SECURITY (fail-closed, §24/§75):
  - A CASUAL / AMBIGUOUS affirmation ("ok", "sure", "yeah", "do it", "go ahead") with NO bound
    action id NEVER authorizes a high-impact action — it returns REFUSED_AMBIGUOUS / NEEDS_BINDING
    and nothing is written.
  - Authorization requires a STRONG approve verb (approve/authorize/confirm) AND the exact pending
    action id present in the reply. Weak "yes" alone, or the id alone, is not enough.
  - Voice/gesture carry NO authority (§75/§128/§129/§130): a voice/gesture confirmation is REFUSED —
    the durable record must come from a typed/authenticated owner action.
  - Injection markers in the reply are scanned (capability.results) and are inert DATA; they can
    never turn a non-confirmation into an authorization.

Pure logic (interpret / build package) is DB-free and testable as a plain ``python3`` script mirroring
test_registry.py; ``authorize`` / ``reject`` are the thin, injectable DB bridge to proposals_store.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from enum import Enum

from app.services.capability.results import _norm, scan_for_injection

# Casual / ambiguous affirmations — these must NEVER, on their own, authorize a consequential action.
_CASUAL = frozenset({
    "ok", "okay", "k", "kk", "sure", "yeah", "yea", "yep", "yes", "ya", "y", "fine", "please",
    "cool", "great", "good", "do it", "doit", "go", "go ahead", "goahead", "alright", "aight",
    "sounds good", "proceed", "continue", "yes please", "ok do it", "yeah do it", "sure thing",
    "make it so", "let's go", "lets go", "run it", "send it",
})

# Strong, explicit approve/reject verbs (the reply must carry one of these to be actionable).
_APPROVE_RE = re.compile(r"\b(approve|approved|approving|authorize|authorized|authorise|confirm|confirmed)\b", re.I)
_REJECT_RE = re.compile(r"\b(reject|rejected|deny|denied|decline|declined|cancel|cancelled|abort|veto)\b", re.I)

# Channels that carry NO authority — a confirmation over these can never produce the durable record (§75).
_UNAUTHORIZED_CHANNELS = frozenset({"voice", "gesture", "speech", "mic", "camera"})


class ConfirmationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"              # explicit approve verb + bound id + text channel → may record
    REJECTED = "REJECTED"                  # explicit reject verb + bound id → durable rejection
    NEEDS_BINDING = "NEEDS_BINDING"        # an approve/reject verb but no bound action id → ask which
    REFUSED_AMBIGUOUS = "REFUSED_AMBIGUOUS"  # casual/weak word, no strong verb → fails closed
    REFUSED_CHANNEL = "REFUSED_CHANNEL"    # voice/gesture cannot authorize (§75) → require typed confirm
    REFUSED_EMPTY = "REFUSED_EMPTY"        # nothing to interpret


@dataclass
class ConfirmationDecision:
    status: str
    authorized: bool                       # true ONLY for AUTHORIZED (the single gate to a durable write)
    action_id: str                         # the pending action id this reply is bound to (if any)
    reason: str
    channel: str = "text"
    injection_flags: list | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["injection_flags"] = self.injection_flags or []
        return d


def _id_bound(utterance: str, pending_action_id: str) -> bool:
    """True iff the exact pending id appears as a standalone token in the reply ("42", "#42", "action 42",
    "proposal-42"). Token-boundary so id 42 is not matched by "420"."""
    pid = str(pending_action_id or "").strip()
    if not pid:
        return False
    return re.search(r"(?<![\w-])#?" + re.escape(pid) + r"(?![\w-])", utterance) is not None


def interpret_confirmation(utterance: str, pending_action_id: str, *, channel: str = "text") -> ConfirmationDecision:
    """Decide whether a reply is an explicit, unambiguous confirmation BOUND to ``pending_action_id``.

    Fail-closed order: empty → voice/gesture channel → strong approve/reject verb + bound id →
    verb-without-id → everything else (casual/weak) refused. Injection markers in the reply are scanned
    and carried as inert data; they never upgrade a non-confirmation into an authorization (§24)."""
    raw = _norm(utterance or "").strip()
    flags = scan_for_injection(raw)
    low = raw.lower()
    ch = (channel or "text").strip().lower()

    if not low:
        return ConfirmationDecision(ConfirmationStatus.REFUSED_EMPTY.value, False, "",
                                    "Empty reply — no confirmation.", ch, flags)

    # §75: voice/gesture never authorize a consequential action, regardless of wording.
    if ch in _UNAUTHORIZED_CHANNELS:
        return ConfirmationDecision(
            ConfirmationStatus.REFUSED_CHANNEL.value, False, str(pending_action_id or ""),
            f"{ch} carries no authority — confirm this action via a typed owner action (§75).", ch, flags)

    has_approve = bool(_APPROVE_RE.search(low))
    has_reject = bool(_REJECT_RE.search(low))
    bound = _id_bound(low, pending_action_id)

    # Reject is fail-safe but still needs the id to write a durable, unambiguous rejection.
    if has_reject:
        if bound:
            return ConfirmationDecision(ConfirmationStatus.REJECTED.value, False, str(pending_action_id),
                                        "Explicit rejection bound to the pending action.", ch, flags)
        return ConfirmationDecision(ConfirmationStatus.NEEDS_BINDING.value, False, "",
                                    "Rejection not bound to a specific pending action id.", ch, flags)

    if has_approve:
        if bound:
            return ConfirmationDecision(ConfirmationStatus.AUTHORIZED.value, True, str(pending_action_id),
                                        "Explicit approval bound to the pending action id.", ch, flags)
        return ConfirmationDecision(
            ConfirmationStatus.NEEDS_BINDING.value, False, "",
            "Approval verb present but no pending action id named — say e.g. 'approve "
            f"{pending_action_id or '<id>'}' to bind it.", ch, flags)

    # No strong verb. A casual word, or a bare id, or anything else → fails closed (never authorizes).
    return ConfirmationDecision(
        ConfirmationStatus.REFUSED_AMBIGUOUS.value, False, "",
        "Ambiguous/casual reply cannot authorize a consequential action — reply with an explicit "
        f"'approve {pending_action_id or '<id>'}' (or 'reject {pending_action_id or '<id>'}').", ch, flags)


# ── §24/§60 inline consequential-action package (reuses owner_review_package / _approval_package shape) ──
def build_approval_request(*, proposal_id, action: str, target: str = "UNSPECIFIED",
                           environment: str = "production", risk: str = "", action_class: str = "",
                           evidence: list | None = None, rollback: str = "", reversible: bool = False,
                           exact_authority: str = "") -> dict:
    """The inline package KAI presents BEFORE a consequential action runs. Descriptive only — carries NO
    authority to execute (authority=OWNER_REQUIRED). ``required_confirmation`` is the exact phrase the
    owner must type to bind an approval to THIS id (the casual-word guard rejects anything else)."""
    pid = str(proposal_id)
    return {
        "ACTION": action or "consequential-action",
        "TARGET": target or "UNSPECIFIED",
        "ENVIRONMENT": environment,
        "RISK": risk or action_class or "UNKNOWN",
        "EVIDENCE": list(evidence or []),
        "ROLLBACK": rollback or ("reversible" if reversible else
                                 "REVERSIBLE_UNKNOWN — owner must confirm a rollback plan before this runs"),
        "EXACT_AUTHORITY_REQUESTED": exact_authority or f"OWNER approval of action {pid} ({action_class or 'HIGH_IMPACT'})",
        "action_class": action_class,
        "authority": "OWNER_REQUIRED",
        "decision": "REQUIRE_APPROVAL",
        "pending_action_id": pid,
        "required_confirmation": f"approve {pid}",
        "provenance": "REAL",
    }


def request_from_proposal(proposal: dict, *, environment: str = "production") -> dict:
    """Build the §24 package from a proposals_store row (its ``action`` JSON holds the descriptive
    fields). No network, no fabrication — missing fields disclaim, never guess."""
    act = (proposal or {}).get("action") or {}
    return build_approval_request(
        proposal_id=proposal.get("id"),
        action=act.get("proposed_action") or proposal.get("title") or "consequential-action",
        target=proposal.get("entity") or "UNSPECIFIED",
        environment=environment,
        risk=act.get("risk") or proposal.get("severity") or "",
        action_class=act.get("action_class") or "",
        evidence=proposal.get("evidence") or act.get("evidence") or [],
        rollback=act.get("rollback") or "",
        reversible=bool(act.get("reversible")),
    )


# ── DB bridge: the ONLY path from a confirmed turn → a durable approval record (proposals_store) ────────
def authorize(proposal_id, *, principal: str, utterance: str, channel: str = "text",
              decider=None, fetch=None) -> dict:
    """Resolve an owner's confirming reply to a DURABLE approval record — ONLY on an explicit, bound,
    text-channel confirmation. Fails CLOSED: any non-AUTHORIZED decision writes nothing and returns the
    decision so the caller can re-ask. ``decider``/``fetch`` are injectable (tests pass fakes); defaults
    are proposals_store.decide / .get. ``principal`` is the authenticated owner (from require_kai_ultra),
    NEVER taken from the reply text."""
    decision = interpret_confirmation(utterance, str(proposal_id), channel=channel)
    if not decision.authorized:
        return {"authorized": False, "record": None, "decision": decision.as_dict(),
                "reason": decision.reason}
    if decider is None or fetch is None:
        from app.services.holding import proposals_store as ps
        decider = decider or ps.decide
        fetch = fetch or ps.get
    existing = fetch(int(proposal_id)) if str(proposal_id).isdigit() else None
    if not existing:
        return {"authorized": False, "record": None, "decision": decision.as_dict(),
                "reason": f"no pending action {proposal_id} to approve"}
    if existing.get("status") != "proposed":
        return {"authorized": False, "record": None, "decision": decision.as_dict(),
                "reason": f"action {proposal_id} is '{existing.get('status')}', not open for approval"}
    record = decider(int(proposal_id), "approved", by=principal or "owner")
    if not record:
        return {"authorized": False, "record": None, "decision": decision.as_dict(),
                "reason": "durable approval write failed (fail-closed)"}
    return {"authorized": True, "record": record, "decision": decision.as_dict(),
            "reason": "explicit bound approval recorded durably (execution remains separately gated)"}


def reject(proposal_id, *, principal: str, utterance: str = "", channel: str = "text",
           reason: str = "", decider=None) -> dict:
    """Durably reject a pending action. A reject verb bound to the id records 'rejected'; anything
    ambiguous is refused (no write). Fail-safe either way (nothing runs)."""
    decision = interpret_confirmation(utterance or f"reject {proposal_id}", str(proposal_id), channel=channel)
    if decision.status != ConfirmationStatus.REJECTED.value:
        return {"rejected": False, "record": None, "decision": decision.as_dict(), "reason": decision.reason}
    if not str(proposal_id).isdigit():   # mirror authorize()'s guard — no ValueError on a non-numeric id
        return {"rejected": False, "record": None, "decision": decision.as_dict(),
                "reason": f"no pending action {proposal_id} to reject"}
    if decider is None:
        from app.services.holding import proposals_store as ps
        decider = ps.decide
    record = decider(int(proposal_id), "rejected", reason=reason or "owner rejected", by=principal or "owner")
    return {"rejected": bool(record), "record": record, "decision": decision.as_dict(),
            "reason": "owner rejection recorded" if record else "reject write failed"}


if __name__ == "__main__":
    from app.services.holding.test_approval_dialog import run
    raise SystemExit(0 if run() else 1)
