# KAI Governed Workforce — Source → Integration SHA Map

Source branch `feat/kai-hook-foundation-phase1` (reviewed impl `97549b8`) →
integration branch `feat/kai-governed-workforce-inert-integration` off
`origin/production` `76137360`. 32 commits via `git cherry-pick -x` + 1 scoped
doc extract = 33 integration commits. Integration HEAD `c8f6fdcf`.

| # | Original SHA | Integration SHA | Subject |
|---|---|---|---|
| 1 | `67fc8debccd9` | `343d36fb256f` | feat(capability-exchange): inert Stage-1 capability manifest + registry |
| 2 | `2f3383fd9d9b` | `f00e5a1372a9` | feat(kai-angular-pilot): DARK Angular workspace skeleton for the governed- |
| 3 | `a194dbacf2c5` | `b20cab4be3c8` | fix(kai-angular-pilot): repin dark pilot Angular 17 → 22 (supported baseli |
| 4 | `c69c4dfd9375` | `b841515e6008` | fix(capability-exchange): address 3 confirmed LOW findings from independen |
| 5 | `ccef12b7d298` | `bb6acf98a583` | docs(kai-plans): controlling-plan checkpoint — hooks + capability-exchange |
| 6 | `d0b80fd7a459` | `560bab003fcc` | feat(hooks): Phase-1 unit #1 — versioned EventEnvelope + HookDefinition co |
| 7 | `6b70d517f839` | `566f857c94b2` | feat(hooks): Phase-1 unit #2 — inert hook registry (event matching, arming |
| 8 | `57f2000841c8` | `2b519c394471` | docs(workforce): Phase-0 controlling plan for the KAI Governed Workforce ( |
| 9 | `e888ae28ec6e` | `d9e50b3de55d` | fix(hooks): make HookRegistry catalog-only — remove the in-process executi |
| 10 | `b409109038e9` | `1bc14e70cfc4` | docs(workforce): embed full requirements in hash-linked companions; remove |
| 11 | `8b91ab0bc6b3` | `87ffbca76a74` | fix(capability-exchange): catalog-only split — remove in-process bind_adap |
| 12 | `a4ac703cdf25` | `fc93e9f678d1` | test(catalog): harden negative-control allowlists to catch private-named e |
| 13 | `1560b85f0bdd` | `3d719f537f8e` | feat(workforce): Phase-1 pure contracts — AgentCharacterManifest schemas ( |
| 14 | `1d112a88f66d` | `b33e95d4f2bd` | feat(workforce): Phase-2 quarantined upstream intake — inventory + evidenc |
| 15 | `32e1710194f9` | `d254b180c87a` | fix(workforce): Phase-2 review Unit 1 — full file accounting; recursive en |
| 16 | `8f837584f161` | `b4b9ef338108` | fix(hooks): Phase-2 review Unit 2 — hardened deploy-skill suggester (false |
| 17 | `95449118c0cf` | `17c9d01704cc` | fix(hooks): Unit-2 independent-review fixes — close 3 residual FP leaks +  |
| 18 | `db9471931192` | `993981b5cd76` | feat(workforce): Phase 3 — normalize 279 upstream + 40 native = 319 INERT  |
| 19 | `2bad9a816f86` | `73c1dae98d81` | fix(workforce): Phase-3 independent-review fixes — enforce injection sanit |
| 20 | `c9841978c1b3` | `083563eceb4c` | feat(workforce): Phase 4 — inert WorkforceCatalog over the 319 normalized  |
| 21 | `fbef8ea46fb2` | `b9ac5241c25b` | fix(workforce): Phase-4 5-lens review fixes — verifier tenant gate, minima |
| 22 | `9eb03398e273` | `d906b1ce3bee` | polish(workforce): canonical order-invariant proposals + accurate unstaffe |
| 23 | `a9f9679c3142` | `89f62740f784` | feat(workforce): Phase 5A — DARK Angular workforce console (source-only, i |
| 24 | `eb5ada667f6e` | `c468fd3283a3` | fix(workforce): Phase-5A UI-honesty+security review fixes (all LOW/NIT; co |
| 25 | `ea1c229310dd` | `df669967f2ed` | fix(workforce): Phase-5A re-review test-teeth — close 3 honesty-test gaps |
| 26 | `49361f03eb0d` | `d8ed4833c52b` | build(workforce): Phase-5A Step 2 — governed Angular dependency admission, |
| 27 | `a72e5a3ff6b0` | `5efec99a1cd4` | fix(workforce): final-review findings — schema/catalog hardening + evidenc |
| 28 | `871c5c8c5f58` | `0aaaa48c0db4` | fix(workforce): final-review round-2 findings — scan completeness, return  |
| 29 | `7f5458da21b2` | `9de3fa5d2797` | fix(workforce): final-review round-3 — reflective autonomy scan (root caus |
| 30 | `1a019a9002e8` | `53fec7de6b3d` | fix(workforce): final-review round-4 — sentience/placeholder scans reflect |
| 31 | `589dd0e924db` | `688135e73719` | fix(workforce): final-review round-5 — hook safeguard test coverage, team- |
| 32 | `97549b83e332` | `fde838baf0ca` | fix(workforce): final-review round-6 — network egress gate parity, cap-poo |
| 33 | `bfe16a1c(scoped)` | `c8f6fdcfe88d` | docs(workforce): add ANGULAR_CAPABILITY_SPEC.md (scoped extract of bfe16a1 |

**12 EXCLUDED source commits** (not transplanted): d2116888 (sol-ui), 3a9da005 +
b58d5c7a (freellmapi), bfe16a1c + 9f78176b (Claude Code dev-hooks; only its
ANGULAR_CAPABILITY_SPEC.md scoped-extracted), fc5fd2cb (Stage-0 audit), 5ca24296
(Stage-0 auth), a995af94 (auth-applied ledger note), 5ab1508b (tenancy), d50ccd46 +
65d56eff + 438ab6d4 (Stage-0/planning ledger prose). See TRANSPLANT_MANIFEST.md.
