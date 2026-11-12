"""Every UPPERCASE name read off `settings` must be DECLARED on Settings.

THE DEFECT THIS CLOSES. `backend/app/config.py` sets `extra="ignore"`, so an environment variable
that matches no declared field is **silently dropped** — no error, no warning — and every reader
gets the default instead. Found 2026-09-13 on production and staging alike:

    declared on Settings: False
    value truthy in-process: False | length: 0
    present in os.environ: True  | env length: 164

A valid 164-character `OPENAI_API_KEY` was installed and completely inert. Three consequences, all
of which looked like something else:

  * `self_model._model()` reported provider UNAVAILABLE, so the KAI chat answered
    "[model unavailable]" — read as a broken model, not a dropped variable.
  * `routers/transcribe.py` returned 503 "OpenAI not configured" with the key configured.
  * `API_KEY` reached `resolve_principal(owner_key=...)` as None, so owner-key auth to App B could
    never match — while `OPERATOR_SESSION_ENABLED=1` and `SESSION_SIGNING_SECRET` were both set,
    which is precisely what made the failure invisible.

`config.py` already warned about this in a comment, and `test_flag_integrity.py` already tested it
— but only for the nine authority flags. The hazard is not specific to flags: it applies to every
name read off `settings`. So this test derives the rule instead of enumerating instances.

An UNDECLARED read is a bug even when the variable is currently unset, because the failure is
silent either way: the day someone sets it, nothing happens and nothing says so.

Parsed with `ast` and stdlib only — the CI gate installs just pytest, and source parsing cannot be
fooled by whatever happens to be in the environment when the test runs.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "backend" / "app" / "config.py"
APP = ROOT / "backend" / "app"

# Names reachable on `settings` that are NOT Settings fields. Each needs a reason.
NOT_A_FIELD = {
    # pydantic-settings / BaseModel API surface, not configuration.
    "Config", "model_config", "model_fields", "model_dump", "model_dump_json",
    "model_validate", "model_copy", "dict", "json", "copy",
}

# DELIBERATELY undeclared — declaring these would BREAK a design that depends on their absence.
# Every entry needs a reason naming the module that relies on it (enforced below).
DELIBERATELY_UNDECLARED = {
    "MONEY_MODE":
        "services/holding/money_state.py exists specifically because MONEY_MODE is undeclared: "
        "_declared() reports UNAVAILABLE rather than a defaulted MOCK, and its self-test asserts "
        "'an UNDECLARED MONEY_MODE reports UNAVAILABLE, never a defaulted MOCK'. status.py, "
        "capabilities_answer.py and self_model.py all honour that. Declaring it would make a "
        "money posture appear source-backed when nothing sets it. Note two readers still carry a "
        "getattr(settings, 'MONEY_MODE', 'MOCK') default — holding_deployment.deployment_view and "
        "digital_twin — which is why the dashboard still shows a defaulted MOCK in its deployment "
        "and twin sections. That is a separate open defect, not a declaration problem.",
}


def _settings_declared() -> set[str]:
    """Every name bound on the Settings class: annotated fields, plain assignments, properties."""
    tree = ast.parse(CONFIG.read_text())
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "Settings"), None)
    assert cls is not None, "Settings class not found in config.py"
    names: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(stmt.name)          # @property and helpers
    return names


def _settings_reads() -> dict[str, set[str]]:
    """UPPERCASE names read off `settings`, mapped to the files that read them.

    Catches both forms actually used in this codebase:
        settings.NAME
        getattr(settings, "NAME", default)
    """
    reads: dict[str, set[str]] = {}

    def note(name: str, path: Path):
        if name.isupper() and name not in NOT_A_FIELD:
            reads.setdefault(name, set()).add(str(path.relative_to(ROOT)))

    for py in APP.rglob("*.py"):
        if py.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(py.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "settings"):
                note(node.attr, py)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name) and node.args[0].id == "settings"
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                note(node.args[1].value, py)
    return reads


def test_the_parsers_find_something():
    """A parser returning nothing — or losing ONE read form — makes the real check vacuous.

    A count threshold alone is not enough: a mutant that broke only the `settings.NAME` branch
    still cleared `>= 10` on the `getattr` branch alone and the suite stayed green. So both forms
    are pinned by a known real reader each.
    """
    declared = _settings_declared()
    assert len(declared) >= 40, "Settings field parse returned too few names"

    reads = _settings_reads()
    assert len(reads) >= 10, "settings-read parse returned too few names"

    # Each pin must be EXCLUSIVE to its form, or the other branch covers for a broken one.
    # OPENAI_API_KEY was the first pin chosen here and was wrong: it is read BOTH ways
    # (settings.OPENAI_API_KEY in transcribe.py, getattr(...) in self_model.py), so a mutant that
    # broke the attribute branch still passed. These two appear in exactly one form each.
    assert "DATABASE_URL" in reads, (
        "the `settings.NAME` attribute branch found nothing — DATABASE_URL is read only that way, "
        "so this form is broken")
    assert "API_KEY" in reads, (
        "the `getattr(settings, \"NAME\", ...)` branch found nothing — API_KEY is read only that "
        "way (routers/admin_chat.py), so this form is broken")


def test_every_setting_read_is_declared():
    declared = _settings_declared()
    undeclared = {n: sorted(f) for n, f in _settings_reads().items()
                  if n not in declared and n not in DELIBERATELY_UNDECLARED}
    assert not undeclared, (
        "These names are read off `settings` but are NOT declared on the Settings class.\n"
        "config.py sets extra=\"ignore\", so the matching env var is SILENTLY DROPPED and every "
        "reader sees the default — the variable can be set correctly in production and do "
        "nothing, with no error anywhere:\n"
        + "\n".join(f"  {n}  <- {', '.join(files)}" for n, files in sorted(undeclared.items()))
    )


def test_the_four_found_in_production_stay_declared():
    """Pin the specific names whose absence motivated this file, so a refactor cannot drop them.

    GH_TOKEN is deliberately NOT here: nothing reads it through Settings (github_scout and
    worker_health read os.environ directly, which extra="ignore" does not affect), so declaring it
    would imply a coverage that does not exist.
    """
    declared = _settings_declared()
    for name in ("API_KEY", "OPENAI_API_KEY", "RELEASE_VERIFIER_SIGNING_SECRET"):
        assert name in declared, (
            f"{name} left Settings. It was found set in production with a real value and read back "
            f"as empty, silently failing every path it guards."
        )


def test_secrets_are_not_given_real_defaults():
    """A declared secret must default to empty — a baked-in default is a credential in source."""
    tree = ast.parse(CONFIG.read_text())
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Settings")
    offenders = []
    for stmt in cls.body:
        if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
            continue
        name = stmt.target.id
        if not any(t in name for t in ("SECRET", "TOKEN", "API_KEY", "PASSWORD", "KEY")):
            continue
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str) \
                and stmt.value.value != "":
            offenders.append(f"{name} = {stmt.value.value[:12]!r}...")
    assert not offenders, (
        "Secret-shaped settings carry a non-empty default, which puts a usable credential in "
        "source and makes a missing env var look configured:\n  " + "\n  ".join(offenders))


def test_deliberate_omissions_carry_a_reason_and_are_still_omitted():
    """An exception must be justified AND still true.

    If someone later declares one of these, the design that depends on its absence breaks silently
    — which is the same failure mode this file exists to prevent, only inverted.
    """
    declared = _settings_declared()
    for name, reason in DELIBERATELY_UNDECLARED.items():
        assert len(reason) > 60, f"{name} needs a real reason, not a placeholder"
        assert name not in declared, (
            f"{name} is listed as deliberately undeclared but IS now declared on Settings. "
            f"Something depends on its absence:\n  {reason}"
        )
