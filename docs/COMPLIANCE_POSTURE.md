# KAI — Compliance Posture for Regulated Domains

**Decision (2026-06-13): RESEARCH-ONLY. No professional advice.**

KAI's professional-domain agents (medical, dental, legal, engineering,
accounting, finance, research) operate strictly as **research / information
assistants**. They:

- surface evidence, standards, guidelines, and references **with citations**;
- ground answers in the user's own indexed documents (`document_search`) and, in
  Phase 2, **verify claims against those sources** before asserting them;
- **never** diagnose, prescribe, give legal/tax/financial advice, or stamp an
  engineering design;
- defer all decisions to a **licensed professional** and say so explicitly.

This matches the product's stated stance (landing page: *"No HIPAA — if you
handle regulated data, please don't use this yet."*).

## What is deliberately NOT enabled

- Advice-giving framing for any regulated domain.
- Ingestion of patient/client PHI/PII into the knowledge base.
- External regulated knowledge connectors (PubMed/EDGAR/CourtListener/IEEE) —
  each needs a per-source ToS/licensing review first.

## To move to ADVISORY (future, gated)

Crossing from research → advice, or handling regulated data, carries
**HIPAA / GDPR / unauthorized-practice (UPL) / professional-liability** exposure.
That transition requires, at minimum:

1. Legal counsel review of scope + disclaimers + liability.
2. A compliance layer: PHI/PII handling + audit, data-retention controls,
   per-domain regulatory mapping (HIPAA/GDPR/etc.).
3. A human-review mode for any recommendation.
4. Explicit operator sign-off recorded here.

Until all four are in place, KAI stays research-only. This file is the durable
record of that decision; the agent system prompts enforce it in
`backend/app/services/presets/registry.py`.
