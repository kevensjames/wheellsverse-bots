"""Regression tests for the hardened deploy-skill suggester (Phase-2 review Unit 2).

Reproduces the exact false trigger (pasted mission / hook-message prose), proves
the OLD naive keyword matcher fires on it while the HARDENED detector does not,
covers every required negative, and proves the detector is pure (no side effects,
cannot deploy/upload/access credentials).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_skill_suggester import should_suggest_deploy  # noqa: E402
import deploy_skill_suggester as mod  # noqa: E402


# --- the original plugin's naive matcher, replicated to PROVE reproduction ---
_NAIVE_KEYWORDS = [
    r"astro deploy", r"deploy.*dag", r"deploy.*airflow", r"deploy.*pipeline",
    r"dag-only deploy", r"dags-only deploy", r"airflow.*ci/cd", r"airflow.*ci cd",
]


def _naive_fires(prompt: str) -> bool:
    low = prompt.lower()
    return any(re.search(k, line) for line in low.splitlines() for k in _NAIVE_KEYWORDS)


# Representative excerpt of the pasted missions + the plugin's own suggestion text
# (all lines that contain deploy-adjacent words but issue NO deploy command).
PASTED_MISSION_EXCERPT = """\
# KAI BUSINESS OPERATING SYSTEM
Build dark and simulated first; KAI remains the sole authority.
- Astro deploy commands (full, DAG-only, image-only, dbt)
- CI/CD setup and GitHub integration
Open-source deployment (Docker Compose, Kubernetes Helm chart)
Do not touch the soak, Istanbul, production, deployed services or existing feature branches.
Do not deploy or enable browser execution.
no deployment occurs;
nothing deployed, flags off.
migrations, merge or deployment;
Live Stripe remains separately owner-gated.
"""


def test_reproduces_false_trigger_and_hardened_suppresses_it():
    # The OLD naive matcher FIRES on this prose (the defect)...
    assert _naive_fires(PASTED_MISSION_EXCERPT) is True
    # ...the HARDENED detector does NOT (no operator deploy command present).
    assert should_suggest_deploy(PASTED_MISSION_EXCERPT) is False


@pytest.mark.parametrize("text", [
    "Do not deploy or enable browser execution.",
    "don't deploy the dags",
    "nothing deployed, flags off",
    "no deployment occurs during this mission",
    "Do not touch production or deployed services.",
    "Open-source deployment (Docker Compose, Kubernetes Helm chart)",
    "- Astro deploy commands (full, DAG-only, image-only, dbt)",  # documentation, not a command
    "migrations, merge or deployment;",
    "See the file deploy.md and the scripts/deploy/ folder.",      # filename/path
    "Load the skill: `/data:deploying-airflow`",                    # skill name / inline code
    "> astro deploy --dag-only   (quoted example in a blockquote)", # blockquote
    "Here is an example:\n```bash\nastro deploy --dags ./dags\n```\nDo not run it.",  # code block
    "",                                                             # empty
])
def test_prose_quotes_code_filenames_negations_do_not_trigger(text):
    assert should_suggest_deploy(text) is False


@pytest.mark.parametrize("text", [
    "Please deploy the dags to astro dev now.",
    "run: astro deploy --dag-only",
    "Deploy the airflow pipeline to production.",
    "ship the DAGs to astro",
])
def test_explicit_operator_commands_do_trigger(text):
    assert should_suggest_deploy(text) is True


def test_detector_is_pure_no_side_effects(tmp_path, monkeypatch):
    # No dangerous I/O primitives in the module source.
    src = Path(mod.__file__).read_text()
    for forbidden in ("subprocess", "os.system", "os.popen", "socket", "requests",
                      "urllib", "open(", "eval(", "exec(", "__import__", "Popen"):
        assert forbidden not in src, f"suggester must not reference {forbidden!r}"
    # Calling it creates no files and returns a bool.
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    r = should_suggest_deploy(PASTED_MISSION_EXCERPT + "\nastro deploy --dag-only\n")
    assert isinstance(r, bool)
    assert set(tmp_path.iterdir()) == before  # zero files created


def test_match_grants_no_authority():
    # A positive match only yields an advisory string; the module exposes no
    # deploy/execute entry point.
    assert should_suggest_deploy("astro deploy --dag-only") is True
    assert "Advisory only" in mod._SUGGESTION
    for forbidden in ("deploy_now", "execute", "run_deploy", "perform"):
        assert not hasattr(mod, forbidden)
