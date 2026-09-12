# Agent Character Contract — the AgentCharacterManifest

Durable, repository-controlled field contract for every workforce character
(imported or KAI-native). Referenced by `KAI_GOVERNED_WORKFORCE_MASTER_PLAN.md`.
No character may be represented by only a name + generic prompt; every character
has a **distinct** name, personality, mission, brain profile, soul constitution,
and workplace assignment. Generic duplicates fail validation.

**"brain" / "soul" are product metaphors, not claims of mind or personhood.**
- *brain* = a KAI-controlled ModelRouter + tool-policy profile (not an independent
  model authority or mind).
- *soul* = a character constitution (values, boundaries, behavioral commitments).
  No claims of consciousness, feelings, personhood, or sentience are permitted.

## AgentCharacterManifest (versioned)

### identity
`id` · `schema_version` · `display_name` · `codename` · `aliases` · `avatar_key`
· `division` · `department` · `seniority` · `role_class` · `source_kind`
(`UPSTREAM` | `KAI_NATIVE`) · `source_path` · `source_commit` · `source_hash`
· `license` · `created_by` · `reviewed_by`.

### personality
`five_to_seven_traits` · `communication_tone` · `working_style` ·
`collaboration_style` · `disagreement_style` · `ambiguity_response` ·
`pressure_response` · `signature_phrase` · `anti_traits` ·
`prohibited_persona_behaviors`.

### mission
`one_sentence_mission` · `responsibilities` · `expected_deliverables` ·
`non_responsibilities` · `success_metrics` · `failure_modes` ·
`escalation_conditions`.

### brain
`profile_id` · `reasoning_class` · `model_router_requirements` ·
`minimum_context` · `maximum_context` · `tool_categories` · `retrieval_policy`
· `memory_access` · `planning_depth` · `temperature_class` · `cost_class` ·
`latency_class` · `fallback_profiles` · `evaluation_suite`.

### soul
`values` · `ethical_commitments` · `truthfulness_rules` · `safety_boundaries` ·
`privacy_commitments` · `user_respect_rules` · `uncertainty_behavior` ·
`refusal_conditions` · `immutable_principles`.

### workplace
`workplace_profile` · `tenant_scope` · `project_scope` · `mission_scope` ·
`filesystem_read_roots` · `filesystem_write_roots` · `scratch_policy` ·
`worktree_policy` · `network_policy` · `allowed_domains` · `secret_references`
· `device_access` · `browser_access` · `external_write_access` · `time_budget`
· `token_budget` · `cost_budget` · `concurrency_limit` · `artifact_locations`
· `evidence_stream` · `cleanup_contract`.
Defaults: network/browser/device/external-write/publishing/messaging/
financial-execution/production-credentials all **DENIED**.

### capabilities
`declared` · `forbidden` · `approval_required` · `reversible_internal` ·
`consequential` · `input_schemas` · `output_schemas` · `evidence_requirements`.

### governance
`status` · `risk_tier` · `effect_class` · `activation_requirements` ·
`approval_policy` · `separation_of_duties` · `independent_reviewer_classes` ·
`kill_control` · `expiry` · `revocation` · `audit_policy`.

## Validation rules (enforced by `test_workforce_schemas.py` — Phase 1)

- Every manifest has all eight sections populated (no section may be empty).
- `display_name` + `codename` unique across the catalog; names deterministically
  derived from `id` (no random renames across builds); collision-checked.
- Generic/placeholder text rejected; unsafe-autonomy language rejected; sentience
  claims rejected; second-orchestrator authority rejected.
- `KAI_NATIVE` characters must NOT claim upstream provenance; `UPSTREAM` characters
  must carry `source_path` + `source_commit` + `source_hash` + `license`.
- Forbidden external effects represented explicitly in `capabilities.forbidden`.
- `status` defaults to `INERT` (or earlier); `AVAILABLE` ≠ authorized for a mission.
