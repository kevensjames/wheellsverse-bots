"""Pure tests for §32 holding-scoped typed memory + the provenance GATE.
Runs against a FAKE in-memory store — NO live pgvector DB needed.
Run: python3 backend/app/services/holding/test_holding_memory.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding.holding_memory import (   # noqa: E402
    HoldingMemory, InMemoryHoldingStore, HoldingMemoryError,
    MemoryCategory, Origin, Verification,
)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _mem():
    """A HoldingMemory backed by a fresh fake store (no DB, no embeddings)."""
    store = InMemoryHoldingStore()
    return HoldingMemory(store, clock=lambda: "2026-09-03T00:00:00+00:00"), store


def _raises(fn):
    try:
        fn()
    except HoldingMemoryError:
        return True
    return False


# ── the GATE: FACT provenance/evidence ───────────────────────────────────────────────────────────
def t_fact_without_provenance_is_refused():
    m, _ = _mem()
    # no origin at all → provenance required → refused
    assert _raises(lambda: m.write(category="FACT", content="prod is healthy", origin=None,
                                   evidence_ref="ev-1")), "missing origin must refuse"
    # an unknown origin string is also refused (not silently accepted)
    assert _raises(lambda: m.write(category="FACT", content="prod is healthy", origin="vibes",
                                   evidence_ref="ev-1")), "unknown origin must refuse"


def t_fact_without_evidence_is_refused():
    m, store = _mem()
    assert _raises(lambda: m.write(category="FACT", content="App B SHA is 4fbfb8e",
                                   origin=Origin.OBSERVED)), "FACT with no evidence_ref must refuse"
    assert store.rows == [], "nothing may be persisted when the GATE refuses"


def t_fact_with_trusted_origin_and_evidence_is_verified():
    m, store = _mem()
    rec = m.write(category=MemoryCategory.FACT, content="App B running SHA is 4fbfb8e",
                  origin=Origin.OBSERVED, evidence_ref="railway:deploy/abc123", company="kai")
    assert rec.verification is Verification.VERIFIED
    assert len(store.rows) == 1 and store.rows[0]["category"] == "FACT"
    assert store.rows[0]["verification"] == "VERIFIED"


# ── the GATE: an LLM claim can NEVER silently become a verified FACT ──────────────────────────────
def t_llm_claim_cannot_become_a_verified_fact():
    m, store = _mem()
    # even WITH a caller-supplied "evidence_ref", an LLM-sourced claim is refused as a FACT —
    # the model's own generation is not itself proof (§32/§76).
    assert _raises(lambda: m.write(category="FACT", content="Sol has 5000 paying customers",
                                   origin=Origin.LLM, evidence_ref="the-model-said-so")), \
        "LLM claim must never be stored as a verified FACT"
    assert store.rows == [], "a refused LLM FACT must not be persisted"


def t_external_claim_cannot_become_a_verified_fact():
    m, _ = _mem()
    assert _raises(lambda: m.write(category="FACT", content="repo README says it is safe",
                                   origin=Origin.EXTERNAL, evidence_ref="README.md")), \
        "EXTERNAL claim must never be a verified FACT"


def t_llm_claim_is_storable_as_unverified_observation():
    """The spec's alternative path: an LLM claim CAN be kept — as UNVERIFIED, in a non-FACT category."""
    m, store = _mem()
    rec = m.write(category=MemoryCategory.ENGINEERING, content="likely the retry loop is O(n^2)",
                  origin=Origin.LLM)
    assert rec.verification is Verification.UNVERIFIED, "LLM claim must land UNVERIFIED"
    assert store.rows[0]["origin"] == "LLM" and store.rows[0]["verification"] == "UNVERIFIED"


def t_verification_is_derived_not_caller_declared():
    """Non-FACT + untrusted origin stays UNVERIFIED even though the caller passed an evidence_ref
    string — trust comes from the origin, not from the caller asserting it."""
    m, _ = _mem()
    rec = m.write(category=MemoryCategory.COMPANY, content="competitor raised a round",
                  origin=Origin.EXTERNAL, evidence_ref="some-blog-url")
    assert rec.verification is Verification.UNVERIFIED


# ── category typing enforced ──────────────────────────────────────────────────────────────────────
def t_invalid_category_is_refused():
    m, _ = _mem()
    assert _raises(lambda: m.write(category="GOSSIP", content="x", origin=Origin.OPERATOR,
                                   evidence_ref="e")), "unknown category must refuse"


def t_all_seven_categories_are_typed():
    names = {c.value for c in MemoryCategory}
    assert names == {"FACT", "DECISION", "MISSION", "PREFERENCE", "INCIDENT", "ENGINEERING", "COMPANY"}, names


def t_empty_content_is_refused():
    m, _ = _mem()
    assert _raises(lambda: m.write(category="DECISION", content="   ", origin=Origin.OPERATOR,
                                   evidence_ref="e")), "empty content must refuse"


# ── verified outcomes recorded to improve future decisions ────────────────────────────────────────
def t_record_outcome_is_verified_and_recallable():
    m, _ = _mem()
    m.write(category="DECISION", content="deploy App B first", origin=Origin.OPERATOR)  # UNVERIFIED note
    out = m.record_outcome(content="App B deploy succeeded, health green 3/3",
                           evidence_ref="cycle:cy-wheellsverse-42", mission_ref="m7", company="kai")
    assert out.origin is Origin.OUTCOME and out.verification is Verification.VERIFIED
    outcomes = m.recall_outcomes(company="kai")
    assert len(outcomes) == 1 and outcomes[0]["evidence_ref"] == "cycle:cy-wheellsverse-42"
    assert "mission:m7" in outcomes[0]["tags"]


def t_record_outcome_requires_evidence():
    m, _ = _mem()
    assert _raises(lambda: m.record_outcome(content="it worked", evidence_ref="")), \
        "an outcome without evidence must refuse"


# ── holding scope + recall filters ────────────────────────────────────────────────────────────────
def t_recall_filters_by_category_and_company_and_verified():
    m, _ = _mem()
    m.write(category="COMPANY", content="Sol is pre-revenue", origin=Origin.OPERATOR,
            evidence_ref="owner-confirmed", company="sol")
    m.write(category="COMPANY", content="rumor about Sol", origin=Origin.EXTERNAL, company="sol")
    m.write(category="INCIDENT", content="App A 502 on cold start", origin=Origin.OBSERVED,
            evidence_ref="log:xyz", company="kai")
    assert len(m.recall(company="sol")) == 2
    assert len(m.recall(category="COMPANY", company="sol")) == 2
    assert len(m.recall(category="INCIDENT")) == 1
    assert len(m.recall(company="sol", verified_only=True)) == 1  # only the operator-confirmed one


def t_records_carry_holding_scope():
    m, store = _mem()
    m.write(category="MISSION", content="certify staging", origin=Origin.DERIVED, evidence_ref="plan:1")
    assert store.rows[0]["scope"] == "holding"


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
