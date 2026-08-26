# KAI Capability Fabric — Routing

The user speaks naturally; KAI decides which capability to use. The user should not need to
remember tool names.

## How routing works

1. **Intent** — `classify_intent()` derives coarse tags (code / docs / security / learning /
   memory / local_model / geo / browser / collaboration / research) from observable keywords.
2. **Candidates** — a capability is a candidate only if it is *selectable* (installed +
   healthy + not disabled) **and** one of its `triggers` appears in the request.
3. **Filter** — governance (`evaluate_policy`) drops anything DENIED; the resource filter drops
   anything the machine can't run.
4. **Rank** — the §28 weighted score orders survivors; conflicts/alternatives collapse to one.
5. **Plan** — dependencies first, then the capability, each with a decision + approval flag +
   a one-line rationale.

## Proven routing (test-backed, §65/§66)

| the user says | KAI routes to | why |
|---------------|---------------|-----|
| "Check the current FastAPI documentation…" | **context7** | docs intent, `documentation` trigger |
| "Verify this page on mobile." | **playwright** | `mobile` / `page` trigger |
| "Analyze this binary from my authorized lab." | **reverse-skill** (approval-gated) | RESTRICTED → REQUIRE_APPROVAL |
| "Show these coordinates on a map." | **geolibre** | `coordinates` / `map` |
| "Learn this PDF." | **book-to-skill** (+ its doc-parser dep first) | learning intent + §60 dependency ordering |
| "Run the strongest model this machine can support locally." | **one** of ollama/airllm | §61 alternatives — lighter/lower-risk wins the tie |
| "Hello there." / "what is 2 + 2" | **nothing** | §66 — no triggers, no capability activated |

## Restraint is a feature (§66/§69)

"Automatic" does **not** mean "activate everything." A greeting or a simple arithmetic request
selects **zero** capabilities. Heavy runtimes stay dormant until genuinely needed and are
stopped afterward.

## Honesty of live routing today

The routing *logic* is built and tested against fixtures. With the **real seed**, only the
native `kai-memory` and `claude-code` are AVAILABLE, so a real request like "map these
coordinates" correctly selects **nothing external** — `geolibre` is upstream-verified but
`EXTERNAL_BLOCKED`, and the Brain will not fake its availability. Live external routing begins
only after a capability is actually installed, health-checked, and certified.

## Fallbacks (§30)

`airllm → ollama`, `jcode → claude-code`, and (at the call site) `context7 → official web docs
if policy permits`. When a required dependency is unavailable, the plan emits a `BLOCKED` step
naming the fallback rather than claiming a verification that did not occur.
