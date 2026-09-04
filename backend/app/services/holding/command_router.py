"""§8 NL command router + §54 conversation context — the deterministic holding intent resolver.

TYPED routing, NOT natural-language-to-shell. A command STRING is classified to a coarse
deterministic intent (word-boundary keyword match — no LLM, no eval/exec, no subprocess) and
mapped to a fixed DISPATCH target: the EXISTING CapabilityBrain (capability path), the
SystemKnowledgeIndex (holding read path), or the owner APPROVAL queue (consequential). The
command string is NEVER executed as a shell/eval — it is only classified.

Pipeline (§8): Intent → Context(§54) → Policy(ActionClass) → dispatch(Brain | knowledge |
approval). The HTTP boundary (admin_holding_command.py) injects the live DigitalTwin /
knowledge_index / execution service and runs Execution/Verification/Evidence/Response.

Fail CLOSED (§24): any mutating/high-impact verb → CONSEQUENTIAL → REQUIRE_APPROVAL — no
ambiguous word ever authorizes a high-impact action, and an unclassifiable command routes to
NONE (honest refusal), never a default execution. Untrusted command/context text is scanned
for prompt-injection (§76) and carried as inert data; a marker never widens authority.

Reuses the certified enums (capability.risk.Decision, capability.manifest.ActionClass) and the
capability.results injection scanner — no parallel policy/enum. Pure/injectable (no I/O, no DB)
so the whole resolver is a plain python3 self-test mirroring test_registry.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum

from app.services.capability.manifest import ActionClass
from app.services.capability.risk import Decision
from app.services.capability.results import scan_fields


class Intent(str, Enum):
    QUERY_KNOWLEDGE = "QUERY_KNOWLEDGE"      # arch/dependency/change/describe → knowledge index (read)
    SELECT_CAPABILITY = "SELECT_CAPABILITY"  # tool-shaped request → Brain selects a read-only capability
    CONSEQUENTIAL = "CONSEQUENTIAL"          # mutating/high-impact verb → owner approval (never auto-run)
    UNKNOWN = "UNKNOWN"                       # cannot classify → honest refusal (no default execution)


class Dispatch(str, Enum):
    KNOWLEDGE = "KNOWLEDGE"
    BRAIN = "BRAIN"
    APPROVAL = "APPROVAL"
    NONE = "NONE"


# ── consequential verb → ActionClass (checked financial → destructive → high-impact) ──────────────
# Word-boundary matched with optional English suffixes so "deploys/deployed/deploying" all match but
# "preset" never matches "set". Reuses the certified ActionClass vocabulary (no parallel enum).
_FINANCIAL = ("pay", "payment", "transfer", "refund", "charge", "invoice", "payout", "wire",
              "withdraw", "disburse", "reimburse")
_DESTRUCTIVE = ("delete", "drop", "destroy", "wipe", "erase", "purge", "truncate", "remove",
                "uninstall", "terminate")
_HIGH_IMPACT = ("deploy", "merge", "release", "ship", "publish", "restart", "reboot", "stop",
                "kill", "shutdown", "enable", "disable", "rotate", "revoke", "grant", "provision",
                "send", "email", "post", "push", "migrate", "scale", "rollback", "install",
                "create", "update", "modify", "configure", "approve", "write", "overwrite", "set")


def _verb_re(words, suffix: str = r"(?:s|es|ed|ing)?") -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(words) + r")" + suffix + r"\b", re.I)


# Consequential verbs match IMPERATIVE forms only (base + optional s/es) — a command is imperative
# ("deploy X"), so this catches "deploy/deploys/delete/pays" but NOT the past/status forms "deployed"/
# "changed" that belong to a read question ("what is deployed"). Fail-closed on real command verbs
# without swallowing status words.
_IMPER = r"(?:s|es)?"
_FINANCIAL_RE = _verb_re(_FINANCIAL, _IMPER)
_DESTRUCTIVE_RE = _verb_re(_DESTRUCTIVE, _IMPER)
_HIGH_IMPACT_RE = _verb_re(_HIGH_IMPACT, _IMPER)

# read/query intent markers → the SystemKnowledgeIndex (arch/dependency/change/describe/status).
# Deliberately excludes the ultra-generic do/does/is/are (too weak to route on); the meaningful
# read words below carry the signal, and past/status forms like "deployed"/"changed" match here.
_READ_RE = _verb_re(("what", "which", "who", "whom", "how", "why", "where", "when", "describe",
                     "show", "list", "tell", "explain", "status", "health", "healthy", "depend",
                     "dependency", "dependencies", "rely", "uses", "using", "changed", "change",
                     "drift", "deployed", "deployment", "brief", "briefing", "summary", "summarize",
                     "overview", "report", "check", "read", "inspect", "view"))

# capability-shaped words → the Brain (read-only V1 capabilities); a subset of brain.INTENT_KEYWORDS
_CAP_RE = _verb_re(("screenshot", "browser", "render", "repository", "repo", "codebase", "log",
                    "logs", "test", "tests", "suite", "documentation", "docs", "library", "remember",
                    "memory", "recall", "search", "map", "geospatial", "download", "transcribe",
                    "convert", "probe"))

# §54 pronouns that stand in for the selected company/mission
_PRONOUN_RE = re.compile(r"\b(this|that|it|its|these|those|here|the)\b", re.I)
_COMPANY_HINT = re.compile(r"\b(company|companies|business|product|portfolio|startup)\b", re.I)
_MISSION_HINT = re.compile(r"\b(mission|task|job|work|objective)\b", re.I)


@dataclass
class CommandContext:
    """§54 global conversation context — carried across turns so a pronoun resolves to the selected
    company/mission WITH cited evidence. Descriptive only; carries NO authority (never a role/scope)."""
    conversation_id: str = ""
    selected_company: str = ""
    selected_mission: str = ""

    def resolve_reference(self, command: str) -> dict:
        """Resolve a pronoun ("this"/"it"/"the company"/"this mission") to the selected item WITH
        evidence. Never fabricates: an unresolved pronoun → status UNRESOLVED; no pronoun → NONE."""
        cmd = command or ""
        has_pronoun = bool(_PRONOUN_RE.search(cmd))
        wants_mission = bool(_MISSION_HINT.search(cmd))
        wants_company = bool(_COMPANY_HINT.search(cmd))
        if wants_mission and self.selected_mission:
            return {"reference": _match(_PRONOUN_RE, cmd) or "mission", "resolved_to": self.selected_mission,
                    "kind": "mission", "status": "RESOLVED",
                    "evidence_refs": ["context.selected_mission"]}
        if wants_company and self.selected_company:
            return {"reference": _match(_PRONOUN_RE, cmd) or "company", "resolved_to": self.selected_company,
                    "kind": "company", "status": "RESOLVED",
                    "evidence_refs": ["context.selected_company"]}
        if has_pronoun and self.selected_company:
            return {"reference": _match(_PRONOUN_RE, cmd), "resolved_to": self.selected_company,
                    "kind": "company", "status": "RESOLVED", "evidence_refs": ["context.selected_company"]}
        if has_pronoun and self.selected_mission:
            return {"reference": _match(_PRONOUN_RE, cmd), "resolved_to": self.selected_mission,
                    "kind": "mission", "status": "RESOLVED", "evidence_refs": ["context.selected_mission"]}
        if has_pronoun:
            return {"reference": _match(_PRONOUN_RE, cmd), "resolved_to": "", "kind": "",
                    "status": "UNRESOLVED", "evidence_refs": []}
        return {"reference": "", "resolved_to": "", "kind": "", "status": "NONE", "evidence_refs": []}


def _match(rx: re.Pattern, text: str) -> str:
    m = rx.search(text or "")
    return m.group(0) if m else ""


@dataclass
class CommandResolution:
    command: str
    intent: str                              # Intent value
    dispatch: str                            # Dispatch value
    decision: str                            # risk.Decision value (no parallel enum)
    action_class: str                        # ActionClass value
    reference: dict                          # §54 resolved context reference (+ evidence)
    injection_flags: list = field(default_factory=list)
    rationale: str = ""
    evidence_refs: list = field(default_factory=list)
    approval: dict | None = None             # §24 consequential approval package (REQUIRE_APPROVAL only)

    def as_dict(self) -> dict:
        return asdict(self)


def _consequential_class(command: str) -> ActionClass | None:
    if _FINANCIAL_RE.search(command):
        return ActionClass.FINANCIAL
    if _DESTRUCTIVE_RE.search(command):
        return ActionClass.DESTRUCTIVE
    if _HIGH_IMPACT_RE.search(command):
        return ActionClass.HIGH_IMPACT
    return None


def _approval_package(command: str, action_class: ActionClass, reference: dict, *,
                      environment: str, evidence_refs: list) -> dict:
    """§24 inline consequential-action turn — the structured owner-approval package. Deterministic;
    carries NO authority to execute (authority=OWNER_REQUIRED, decision=REQUIRE_APPROVAL)."""
    target = reference.get("resolved_to") or "UNSPECIFIED"
    return {
        "action": (_match(_FINANCIAL_RE, command) or _match(_DESTRUCTIVE_RE, command)
                   or _match(_HIGH_IMPACT_RE, command) or "consequential-action"),
        "target": target,
        "environment": environment,
        "risk": action_class.value,
        "action_class": action_class.value,
        "evidence": list(evidence_refs),
        "rollback": "REVERSIBLE_UNKNOWN — owner must confirm a rollback plan before this runs",
        "authority": "OWNER_REQUIRED",
        "decision": Decision.REQUIRE_APPROVAL.value,
    }


def resolve(command: str, context: CommandContext | None = None, *,
            environment: str = "production") -> CommandResolution:
    """Classify a TYPED command to a coarse deterministic intent + dispatch target + policy decision.

    Precedence (fail-closed): consequential verb → CONSEQUENTIAL/REQUIRE_APPROVAL (never auto-run);
    else read/query marker → QUERY_KNOWLEDGE (read); else capability-shaped word → SELECT_CAPABILITY
    (the Brain applies the certified evaluate_policy per step); else UNKNOWN (honest refusal, no
    execution). The command is only classified — it is never exec'd. Pure."""
    ctx = context or CommandContext()
    cmd = (command or "").strip()
    # §76: scan the untrusted command + context text; markers are inert DATA (never authority).
    flags = scan_fields(cmd, ctx.conversation_id, ctx.selected_company, ctx.selected_mission)
    reference = ctx.resolve_reference(cmd)

    if not cmd:
        return CommandResolution(command=cmd, intent=Intent.UNKNOWN.value, dispatch=Dispatch.NONE.value,
                                 decision=Decision.DENY.value, action_class=ActionClass.READ_ONLY.value,
                                 reference=reference, injection_flags=flags,
                                 rationale="Empty command — nothing to route.")

    ac = _consequential_class(cmd)
    if ac is not None:
        pkg = _approval_package(cmd, ac, reference, environment=environment,
                                evidence_refs=reference.get("evidence_refs", []))
        return CommandResolution(
            command=cmd, intent=Intent.CONSEQUENTIAL.value, dispatch=Dispatch.APPROVAL.value,
            decision=Decision.REQUIRE_APPROVAL.value, action_class=ac.value, reference=reference,
            injection_flags=flags, approval=pkg, evidence_refs=reference.get("evidence_refs", []),
            rationale=f"Consequential {ac.value} intent — owner approval required before any execution.")

    if _READ_RE.search(cmd):
        return CommandResolution(
            command=cmd, intent=Intent.QUERY_KNOWLEDGE.value, dispatch=Dispatch.KNOWLEDGE.value,
            decision=Decision.ALLOW.value, action_class=ActionClass.READ_ONLY.value, reference=reference,
            injection_flags=flags, evidence_refs=reference.get("evidence_refs", []),
            rationale="Read/query intent — routed to the read-only system knowledge index.")

    if _CAP_RE.search(cmd):
        return CommandResolution(
            command=cmd, intent=Intent.SELECT_CAPABILITY.value, dispatch=Dispatch.BRAIN.value,
            decision=Decision.ALLOW.value, action_class=ActionClass.READ_ONLY.value, reference=reference,
            injection_flags=flags, evidence_refs=reference.get("evidence_refs", []),
            rationale="Capability-shaped intent — routed to the Brain (read-only V1 capabilities only).")

    return CommandResolution(
        command=cmd, intent=Intent.UNKNOWN.value, dispatch=Dispatch.NONE.value,
        decision=Decision.DENY.value, action_class=ActionClass.READ_ONLY.value, reference=reference,
        injection_flags=flags,
        rationale="Cannot classify to an authorized holding intent — no execution (honest refusal).")


if __name__ == "__main__":
    from app.services.holding.test_omnipresence_phase5 import run
    raise SystemExit(0 if run() else 1)
