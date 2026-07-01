# KAI v1 — the AGI-directional blueprint

> **Honest framing (read first).** True AGI is **not buildable in 2026 by anyone** —
> frontier models score ~0% on ARC-AGI-3's interactive learn-by-doing test, and the
> core prerequisites (continual learning, grounded understanding, durable autonomy,
> open-ended generalization) are open *research* problems, not engineering tasks.
> This blueprint does **not** claim to build AGI. It builds the **best 2026-achievable
> approximation** of each AGI condition — a superb autonomous AI *agent + companion*,
> "AGI-directional." Pitch it that way and it's credible and fundable; call it "AGI"
> and a technical reviewer (or an investor's DD) will catch it instantly.

**The encouraging truth:** KAI already has ~70% of the parts. v1 is mostly **wiring
existing subsystems into closed loops**, not inventing from scratch.

## The six conditions → best approximation

| # | AGI condition | Approximation | Existing KAI pieces | New piece | Honest ceiling |
|---|---|---|---|---|---|
| 1 | Open-ended generalization | Tool-augmented reasoning + retrieval + **verify-and-retry** + test-time search (try N, keep the verified one) + multi-model | `tools/` (~30), `memory`+`rag`, `self_correction`, `router` | "try→verify→pick-best" loop | Broadens coverage + kills brittleness *in-domain*; not novel abstract problems |
| 2 | Continual learning | Memory **lifecycle** (store→update→summarize→**discard**) + **background extraction** from every chat + approved-lessons loop + **periodic LoRA** on accumulated data | `memory` (pgvector), `learning`, `kg` | Background extractor + memory forgetting + quarterly LoRA | Improves over time; not true *online* weight learning |
| 3 | Persistent self-directed goals | Durable goal store + plan→act→**verify**→report across sessions, with **human gates** | `planning`, `ceo`, `digest`, schedulers | Persistent checkpointed goal loop | Pursues *bounded, scoped* goals over days; not open-ended agency |
| 4 | Grounded world-model (anti-hallucination) | RAG over trusted docs + **KG as verified fact store** + **verify-don't-trust** (tools confirm facts before KAI asserts) | `rag`, `verify_claim`, `document_search`, `kg`, connectors | Route claims through verify_claim+KG before answering | Cuts hallucination in *your* domains; no general physical grounding |
| 5 | Recursive self-improvement | **Human-reviewed** self-improvement: KAI critiques itself, drafts its own tools/prompts/lessons → **operator approves** → applied | `self_correction`, `learning`, `adapter_codegen`, `self_heal`, `failure_memory` | failure→proposal→approval loop | KAI *proposes* upgrades; a human approves. **Never** autonomous |
| 6 | Reliable reasoning / no hallucination | **Verify-before-answer**: draft→self-critique→tool-verify→**confidence gate→refuse if unsure**→cite | `self_correction`, `verify_claim`, `router` (multi-model) | verify-before-answer wrapper | Much more trustworthy; can't eliminate hallucination |

## Why v1 is integration, not invention

Five of six conditions reduce to the **same three moves**, all of which KAI *already
implements as subsystems* — they just aren't wired into automatic closed loops yet:

1. **A verify loop** — `self_correction` as an adversarial checker.
2. **Grounding** — KG + RAG + tools that *confirm* facts.
3. **A human-gated improvement loop** — propose → operator approves → apply.

The **governance floor is the feature, not the obstacle**: "a human approves
irreversible / money / self-modifying actions" is exactly what separates a fundable
autonomous system from a dangerous one (Character.AI lawsuits, Replika's €5M fine).

## Prioritized build order (each ships independently)

1. **Verify-before-answer wrapper** (#6, #1) — highest trust ROI. *Small.*
2. **Grounding pass** (#4) — claims through verify_claim+kg; citation mode. *Medium.*
3. **Background memory extractor + lifecycle** (#2) — the "learns over time" feel. *Medium.*
4. **Persistent goal loop** (#3) — ceo+planning → checkpointed cross-session pursuer. *Large.*
5. **Human-gated self-improvement loop** (#5) — failure_memory→adapter_codegen→approve. *Large, safety-critical.*
6. **Periodic LoRA cadence** (#2 deep) — real weight updates on approved data. *XL, later.*

## The two non-negotiables

- **The ceiling is real** — superb autonomous companion, *not* AGI. Frame honestly.
- **The safety line is absolute** — #3 and #5 must *always* keep the human gate on
  money + irreversible + self-modifying actions. Removing it is the failure mode, not
  the goal.

## Product context (from the App-Store review)

Before ANY of this ships to end users: **Step 0 (consumer/operator split) is done**
(`KAI_PROFILE`). Then multi-user scale-out (Redis limiter, Celery-leader schedulers,
SQLite→Postgres, per-user spend caps that *refuse* over budget) + the safety/compliance
layer (moderation, crisis handling, age gate, consent, DSAR) — then the RN/Expo app.
~4–6 months to a defensible v1. The economic ceiling (flat-unlimited frontier chat is
unprofitable) forces cost tiering + budgets to ship *with* v1.

---
*Generated 2026-07-01. See memory `kai_agi_vision` and the daemon audit
`KAI_DAEMON_AUDIT_2026-06-29.md`.*
