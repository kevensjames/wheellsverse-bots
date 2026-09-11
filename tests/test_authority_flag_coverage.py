"""Every KAI runtime flag must be reported by at least one surface.

THE DEFECT THIS CLOSES. `KAI_COMPUTER_OPS_ENABLED` is the sole gate for the computer-operations
device plane — `backend/app/main.py` mounts `admin_computer_ops` + `device_connector` on it,
exposing mission creation, device enrolment and elevated-scope grants. It appeared in NONE of the
three reporting surfaces: `self_model.FLAG_KEYS`, `holding_deployment.FEATURE_REGISTRY`, or
`brakes.py`. So no dashboard, audit or status endpoint reported its state at all.

That is precisely the hazard both modules already warn about in their own comments:

  self_model.py     "...it was absent here, so NO surface reported it:
                     the one reader must cover every real flag."
  holding_deployment.py  "...a flag it omits has no reported state at all — the operator cannot
                          tell an OFF feature from an unreported one."

`KAI_CAMERA_ENABLED` had been added earlier for exactly this reason. Adding one more flag by hand
fixes today and not tomorrow, so this test derives the requirement instead of restating it: every
bool `KAI_*` setting declared in config.py must be covered by a reporting surface, or be listed
below as a reviewed, deliberate exclusion. A new flag that is neither fails here — loudly, in CI —
rather than silently becoming unreportable.

Parsed with `ast`, not regex: a line-oriented match cannot see a multi-line call, which is how an
earlier guard in this repo missed a multi-line logging statement. No project dependencies are
imported — the CI gate installs only pytest, and source parsing cannot be fooled by environment.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "backend" / "app" / "config.py"
SELF_MODEL = ROOT / "backend" / "app" / "services" / "holding" / "self_model.py"
REGISTRY = ROOT / "backend" / "app" / "services" / "holding" / "holding_deployment.py"

# Reviewed and deliberately NOT given a reporting row. Adding a name here is a decision that shows
# up in review; leaving a flag out of both surfaces without listing it here is a bug.
# Currently EMPTY, and that is the target state: as of this commit every KAI_* bool flag declared in
# config.py is reported by FLAG_KEYS or FEATURE_REGISTRY. The mechanism exists so that a future
# deliberate omission is a reviewed line of code with a stated reason, rather than an accident nobody
# sees. test_exclusions_are_not_redundant keeps it honest: you cannot park an already-reported flag
# here to make a failure go away.
UNREPORTED_BY_DESIGN: dict[str, str] = {}


def _bool_settings() -> set[str]:
    """Every `NAME: bool = ...` declared on the Settings class."""
    tree = ast.parse(CONFIG.read_text())
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                ann = stmt.annotation
                if isinstance(ann, ast.Name) and ann.id == "bool":
                    out.add(stmt.target.id)
    return out


def _flag_keys() -> set[str]:
    tree = ast.parse(SELF_MODEL.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "FLAG_KEYS" for t in node.targets):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    raise AssertionError("FLAG_KEYS not found — did self_model.py change shape?")


def _registry_flags() -> set[str]:
    """The runtime_flag of every Feature(...) row (5th positional arg, or the keyword)."""
    tree = ast.parse(REGISTRY.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Feature":
            if len(node.args) >= 5 and isinstance(node.args[4], ast.Constant):
                out.add(node.args[4].value)
            for kw in node.keywords:
                if kw.arg == "runtime_flag" and isinstance(kw.value, ast.Constant):
                    out.add(kw.value.value)
    return out


def test_the_parsers_actually_find_something():
    """A parser that silently returns nothing would make every check below vacuously pass."""
    assert len(_bool_settings()) >= 15, "config.py bool parse returned too few settings"
    assert len(_flag_keys()) >= 15, "FLAG_KEYS parse returned too few entries"
    assert len(_registry_flags()) >= 10, "FEATURE_REGISTRY parse returned too few rows"


def test_every_kai_flag_is_reported_by_some_surface():
    reported = _flag_keys() | _registry_flags() | set(UNREPORTED_BY_DESIGN)
    unreported = sorted(
        f for f in _bool_settings()
        if f.startswith("KAI_") and f not in reported
    )
    assert not unreported, (
        "These KAI flags are declared in config.py but reported by NO surface — "
        "neither self_model.FLAG_KEYS nor holding_deployment.FEATURE_REGISTRY:\n  "
        + "\n  ".join(unreported)
        + "\n\nAn unreported flag cannot be distinguished from a disabled one by any dashboard, "
          "audit or status endpoint. Add it to FLAG_KEYS (authority) or FEATURE_REGISTRY "
          "(surface/capability), or list it in UNREPORTED_BY_DESIGN with a reason."
    )


def test_the_device_control_gate_is_reported():
    """Pin the specific flag whose absence motivated this file, so a refactor cannot quietly drop it."""
    assert "KAI_COMPUTER_OPS_ENABLED" in _flag_keys(), (
        "KAI_COMPUTER_OPS_ENABLED left self_model.FLAG_KEYS. It is the sole gate for the "
        "computer-operations device plane (mission creation, device enrolment, elevated-scope grants)."
    )
    assert "KAI_COMPUTER_OPS_ENABLED" in _registry_flags(), (
        "KAI_COMPUTER_OPS_ENABLED left FEATURE_REGISTRY — the dashboard's only per-feature "
        "'deployed vs enabled' row."
    )


def test_exclusions_are_real_flags():
    """An exclusion for a flag that no longer exists is stale cover — it hides nothing and misleads."""
    declared = _bool_settings()
    stale = sorted(f for f in UNREPORTED_BY_DESIGN if f not in declared)
    assert not stale, f"UNREPORTED_BY_DESIGN names flags that config.py no longer declares: {stale}"


def test_exclusions_are_not_redundant():
    """An exclusion for a flag that IS reported would let a real omission hide behind a stale entry."""
    reported = _flag_keys() | _registry_flags()
    redundant = sorted(f for f in UNREPORTED_BY_DESIGN if f in reported)
    assert not redundant, (
        "These flags are listed as deliberately unreported but ARE reported by a surface — "
        f"remove them from UNREPORTED_BY_DESIGN: {redundant}"
    )
