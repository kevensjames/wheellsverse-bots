# Deploy-Hook Hardening — Phase-2 Review Unit 2

**Status:** `DEPLOY_HOOK_HARDENED_LOCALLY` — a repo-owned, fail-closed replacement
detector + regression suite. Advisory only; no deployment/upload/credential/external
effect exists anywhere in this unit. The vendored plugin hook is **not** edited
(it is clobbered on plugin update and exists in triplicate); disabling it is an
operator settings action, recommended below.

## 1. The defect (exactly why quoted prose triggers it)

The vendored Claude-plugin hook

```
~/.claude/plugins/cache/claude-plugins-official/data/0.1.0/skills/airflow/hooks/airflow-skill-suggester.sh
```

(a `UserPromptSubmit` hook; identical copies also under `data-engineering/` and
`astronomer-data-agents/`) decides "the user is asking to deploy" by **keyword
presence in lowercased prose**, not by parsing a command. Three lines cause it:

| Line | Code | Effect |
|---|---|---|
| 8 | `PROMPT_LOWER=$(echo "$USER_PROMPT" \| tr '[:upper:]' '[:lower:]')` | Lowercases the **entire raw prompt** — case can no longer separate a command from quoted prose. |
| 16–25 | `DEPLOY_KEYWORDS=("astro deploy" "deploy.*dag" "deploy.*airflow" "deploy.*pipeline" …)` | Unanchored regex fragments. `deploy.*dag` matches any line where "deploy" precedes "dag" *anywhere*. |
| 27–28 | `for keyword …; do if echo "$PROMPT_LOWER" \| grep -qE "$keyword"; then …` | Per-line `grep -qE`: a **match anywhere on any line** fires the suggestion. |

Because the match is substring-level on lowercased text, the hook fires on:

- **quoted documentation** — e.g. its *own* emitted line 33,
  `Astro deploy commands (full, DAG-only, image-only, dbt)`, matches `astro deploy`;
- **negations** — `Do not deploy`, `nothing deployed`, `no deployment`, `deployed services`;
- **markdown / fenced code** — a `\`\`\`bash\nastro deploy …\n\`\`\`` example;
- **filenames / paths** — `deploy.md`, `scripts/deploy/`;
- any mission paragraph that merely *describes* deployment.

Root cause in one line: **a mention of deployment is treated as a request to
deploy.** A description, a prohibition, or an example is not an operator command.

## 2. The hardened replacement

`scripts/hooks/deploy_skill_suggester.py` — `should_suggest_deploy(prompt) -> bool`,
pure (string → bool), fails closed. Required behaviors (all covered by tests):

1. **Quoted / markdown / code never triggers.** Fenced ```` ``` ```` / `~~~` blocks,
   `inline code`, and `>` blockquote lines are stripped before any matching.
2. **Negations & deployment-state never trigger.** `do not / don't / never / no /
   stop … deploy`, and the state phrases `nothing deployed`, `no deployment`,
   `deployed services`, are guarded out.
3. **Documentation phrases never trigger.** The literal CLI `astro deploy` fires,
   but `astro deploy commands` (documentation, as in the vendored hook's own text)
   is explicitly excluded.
4. **Only an explicit operator command triggers** — either the `astro deploy` CLI,
   or an imperative `deploy/redeploy/ship/release/roll out` + a deploy target
   (`dag/dags/airflow/pipeline/image/to astro/to prod`).
5. **A match grants no authority and performs no action.** A positive result only
   prints an advisory string to stdout; the module references no `subprocess`,
   `os.system`, `socket`, `requests`, `urllib`, file `open(`, `eval`/`exec`, or
   `__import__`, and exposes no deploy/execute entry point. Real deployment stays
   behind KAI's own owner-authorization + approval gates, and **is not authorized
   here.**

`main()` reads stdin and, only on a true result, prints the advisory. It never
blocks, never deploys.

## 3. Proof (regression suite)

`scripts/hooks/test_deploy_skill_suggester.py` — 20 tests, all green under the
branch-local venv:

```
/Users/jhonwheeler/kai-hooks-venv/bin/python -m pytest scripts/hooks/test_deploy_skill_suggester.py -q
# 20 passed
```

Key tests:

- **Reproduction.** `test_reproduces_false_trigger_and_hardened_suppresses_it`
  feeds a representative excerpt of the exact pasted missions (including
  `- Astro deploy commands (full, DAG-only, image-only, dbt)`, `Do not deploy …`,
  `nothing deployed`, `deployed services`, `Open-source deployment …`) through an
  **inline replica of the vendored naive matcher** (asserts it FIRES — defect
  reproduced) and through `should_suggest_deploy` (asserts it does NOT).
- **Negatives.** Prose, negations, blockquotes, fenced code, filenames, the
  `/data:deploying-airflow` skill token, and empty input all return `False`.
- **Positives.** Genuine operator commands (`astro deploy --dag-only`,
  `deploy the dags to astro dev now`, `ship the DAGs to astro`) return `True`.
- **Zero side effects.** `test_detector_is_pure_no_side_effects` greps the module
  source for a wide set of dangerous primitives (subprocess/network/`open(`/`eval`/
  `os.`/`pathlib`/`write_text`/delete — asserts all absent) and asserts a call
  creates no files. `test_match_grants_no_authority` asserts a match yields only
  the advisory string, and `test_module_exposes_only_known_safe_callables`
  **allowlists** the module's public callables to exactly `should_suggest_deploy`
  + `main` — any new deploy/execute/upload entry point fails it.

## 4. Operator recommendation (vendored plugin — NOT done here)

The vendored hook is not editable as part of this changeset: it is overwritten on
plugin update and exists in three identical copies. To stop the false advisories at
the source, an operator may disable the `UserPromptSubmit` hook for the
`data` / `data-engineering` / `astronomer-data-agents` plugins in Claude Code hook
settings. This is a settings action, left to the owner. The repo-owned hardened
detector above is the durable, reviewed artifact; it does not auto-install itself
into any hook runner.

## 5. Ceiling

Nothing merged, deployed, migrated, or enabled. No adapter/handler/worker/router.
`KAI_BROWSER_OPS_ENABLED=false`. Soak + Istanbul untouched. This unit adds only a
pure detector, its tests, and this document.
