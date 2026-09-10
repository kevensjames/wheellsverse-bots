"""money_center carries the only `shell=True` sinks in the repository. This pins their containment.

THE SINK IS REAL AND STILL UNPATCHED on production:

    money_center/dashboard.py:484    subprocess.Popen(cmd, shell=True, cwd=wdir, ...)
    money_center/dashboard.py:512    subprocess.run(cmd, shell=True, timeout=10)
    money_center/cli.py:165, :193    the same two, again

`cmd` is `run_command`, an attacker-controlled form field on `POST /add` that `registry.validate()`
never inspects — it checks `id`, `category`, `status` and `monthly_estimate_usd` and nothing else.
Neither `/add` nor `/start/<id>` has any authentication, and `dashboard.py:552` defaults `--host` to
`0.0.0.0`. It is a stored command injection with no auth in front of it.

WHY IT IS NOT A PRODUCTION INCIDENT. It is unreachable from either deployed app:

  - no deployed app imports the package. `main.py`'s three imports are function-local, inside
    `_launch_money_center()` and the `--money-cli` branch. `money_center/__init__.py` is empty.
  - no Flask app is mounted into either FastAPI app — `WSGIMiddleware` appears nowhere in the repo.
  - no deployment artifact has ever referenced it, across the ENTIRE git history: `git log --all -S`
    over Dockerfile, railway.json, nixpacks.toml, deploy/ and Procfile returns nothing.
  - it `sys.exit(1)`s unless `/Volumes/Wheellsverse` is mounted (`registry.check_ssd()`), so it
    cannot run in a Linux container at all.

WHAT THIS FILE ACTUALLY GUARDS. Reachability was an accident of nobody having wired it up, and an
accident can be undone by a future edit. These tests turn each leg of that argument into something
that fails loudly:

  1. the deployed apps do not import it,
  2. no deployment artifact starts it,
  3. its Python is excluded from the App A container image,
  4. and `GET /api/money/assets` — the one production route that touches money_center DATA — stays
     a field-whitelisted read that never exposes `run_command` or `stop_command`.

Point 3 matters even though the code is dormant: `.dockerignore` did not exclude it and the
Dockerfile does `COPY . .`, so the vulnerable source was being baked into the production image. That
is not exploitable on its own, but it hands a post-exploitation convenience to anyone who gets code
execution by another route. `assets.json` deliberately STAYS in the image — the route reads it, and
the JSON is data, not a sink.

This file also exists so `.github/workflows/phase0-gate.yml` has something real to run. That gate was
"present-guarded": it globbed for three security suites, found none of them, printed "Nothing to
run" and exited 0 — reporting green while executing zero security tests. Its own comment predicted
exactly that failure mode.
"""
import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    p = REPO / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


# ── 1. the sink still exists, so this file is guarding something real ─────────────────────────────
def test_the_shell_true_sinks_are_where_this_file_says_they_are():
    """If money_center is ever hardened, this test fails and the whole file should be revisited —
    a containment test for a vulnerability that no longer exists is misleading documentation."""
    dashboard = _read("money_center/dashboard.py")
    if not dashboard:
        return  # already removed from the repo; nothing to contain
    assert "shell=True" in dashboard, (
        "money_center/dashboard.py no longer uses shell=True — the sink this file contains is gone, "
        "so re-read this file's premise instead of trusting its conclusion")


def test_money_center_holds_the_only_shell_true_in_deployed_code():
    """The property that makes this package the one scanners flag. If `shell=True` appears in code
    that IS deployed, that is a far more serious finding than money_center itself."""
    offenders = []
    for d in ("core", "backend/app", "narai"):
        root = REPO / d
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if "test" in py.name:
                continue
            if "shell=True" in py.read_text(encoding="utf-8", errors="replace"):
                offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], f"shell=True in DEPLOYED code: {offenders}"


# ── 2. no deployed app imports it ─────────────────────────────────────────────────────────────────
def test_no_deployed_app_imports_money_center_at_module_level():
    """A module-level import would load the package on every boot of a deployed app. The three
    imports in main.py are function-local and on CLI-only branches, which is why they are ignored
    here — but a top-level one must never appear."""
    for entry in ("core/api.py", "backend/app/main.py", "main.py"):
        src = _read(entry)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in tree.body:            # module level ONLY, not nested in a function
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "money_center" for n in names), \
                f"{entry} imports money_center at module level — it would load on every boot"


# ── 3. no deployment artifact starts it ───────────────────────────────────────────────────────────
def test_no_deployment_artifact_starts_money_center():
    artifacts = ["Dockerfile", "railway.json", "nixpacks.toml", "Procfile",
                 "deploy/railway.json", "backend/Dockerfile.staging"]
    for rel in artifacts:
        src = _read(rel)
        if not src:
            continue
        assert "money_center" not in src and "--money" not in src, \
            f"{rel} references money_center — it must never be a deployed process"


# ── 4. its Python is excluded from the container image ────────────────────────────────────────────
def test_money_center_python_is_excluded_from_the_image():
    """The Dockerfile does `COPY . .`, so anything not in .dockerignore is baked into production."""
    ignore = _read(".dockerignore")
    assert ignore, ".dockerignore is missing — `COPY . .` would bake the whole tree into the image"
    patterns = [ln.strip() for ln in ignore.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    assert any(p.startswith("money_center/") and p.endswith(".py") for p in patterns), (
        "no .dockerignore rule excludes money_center Python. The Dockerfile is `COPY . .`, so the "
        f"shell=True sinks ship inside the App A image. Patterns present: {patterns[-8:]}")


def test_the_assets_data_file_is_still_shipped():
    """assets.json must NOT be excluded — GET /api/money/assets reads it. The exclusion targets the
    sinks, not the data, and over-excluding would break a working production route."""
    ignore = _read(".dockerignore")
    for line in ignore.splitlines():
        s = line.strip()
        if s.startswith("#") or not s:
            continue
        assert s not in ("money_center", "money_center/", "money_center/*", "money_center/**"), (
            f"'{s}' excludes the whole package including assets.json, which "
            "GET /api/money/assets reads at runtime")


# ── 5. the one production route touching money_center data stays a whitelisted read ───────────────
def test_the_money_assets_route_never_exposes_the_command_fields():
    """`run_command` and `stop_command` are the injection payloads. The route builds its response
    from an explicit key list; if it ever returns the raw record, the stored commands leak."""
    api = _read("core/api.py")
    m = re.search(r'@app\.get\("/api/money/assets"\).*?(?=\n@app\.)', api, re.S)
    assert m, "GET /api/money/assets not found — if it moved, re-point this test"
    handler = m.group(0)
    assert "run_command" not in handler and "stop_command" not in handler, \
        "the money assets route now references the command fields — it must stay field-whitelisted"
    assert ".write_text(" not in handler and "json.dump" not in handler, \
        "the money assets route writes — it must remain read-only, or it becomes a poisoning primitive"
