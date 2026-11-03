"""Pre-commit Semgrep gate: scripts/hooks/pre-commit-scan.sh.

Runs the hook the way Claude Code does (PreToolUse JSON on stdin) inside a
throwaway git repo.

- Stub tests put fake `semgrep` and `curl` executables first on PATH. They
  check the hook's decisions (which rules, how each Semgrep exit code is
  reported) with no network and no Semgrep install.
- `real_semgrep` tests run the installed Semgrep against the repo's local
  rules, offline. They skip when Semgrep is not on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "hooks" / "pre-commit-scan.sh"
LOCAL_RULES = ROOT / ".semgrep" / "rules.yml"
BYPASS_FLAGS = (
    Path("/tmp/.brain-precommit-passed"),
    Path("/tmp/.opsera-pre-commit-scan-passed"),
)
COMMIT = {"tool_name": "Bash", "tool_input": {"command": "git commit -m test"}}

real_semgrep = pytest.mark.skipif(
    shutil.which("semgrep") is None, reason="semgrep not installed"
)

STUB_SEMGREP = """#!/bin/bash
# Test double: records its arguments, writes the JSON report the test asked
# for, prints the text output, exits with the requested code.
printf '%s\\n' "$@" > "$STUB_DIR/semgrep.args"
for arg in "$@"; do
  case "$arg" in --json-output=*) report="${arg#--json-output=}" ;; esac
done
if [ -n "${STUB_SEMGREP_JSON:-}" ] && [ -n "${report:-}" ]; then
  printf '%s' "$STUB_SEMGREP_JSON" > "$report"
fi
if [ -n "${STUB_SEMGREP_TEXT:-}" ]; then printf '%s\\n' "$STUB_SEMGREP_TEXT"; fi
exit "${STUB_SEMGREP_RC:-0}"
"""

STUB_CURL = """#!/bin/bash
# Test double: prints the HTTP code the test asked for (the hook reads it
# via -w '%{http_code}') and exits with the requested code.
printf '%s\\n' "$@" > "$STUB_DIR/curl.args"
printf '%s' "${STUB_CURL_CODE:-200}"
exit "${STUB_CURL_RC:-0}"
"""


@pytest.fixture(autouse=True)
def _no_bypass_flag():
    live = [str(flag) for flag in BYPASS_FLAGS if flag.exists()]
    if live:
        pytest.skip(f"bypass flag present ({', '.join(live)}); it would skip the scan")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture
def stubs(tmp_path):
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for name, body in (("semgrep", STUB_SEMGREP), ("curl", STUB_CURL)):
        exe = bin_dir / name
        exe.write_text(body)
        exe.chmod(0o755)
    return bin_dir


def stage(repo: Path, relpath: str, content: str) -> None:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    subprocess.run(["git", "add", relpath], cwd=repo, check=True)


def run_hook(cwd: Path, payload=COMMIT, stubs: Path | None = None,
             hook: Path = HOOK, **env_overrides: str):
    env = dict(os.environ)
    env.pop("BRAIN_PRECOMMIT_OFFLINE", None)
    if stubs is not None:
        env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
        env["STUB_DIR"] = str(stubs)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(hook)], input=json.dumps(payload), cwd=cwd, env=env,
        capture_output=True, text=True, timeout=120,
    )


def semgrep_args(stubs: Path) -> list[str]:
    return (stubs / "semgrep.args").read_text().splitlines()


# ── Rule selection ──────────────────────────────────────────────────────────

def test_non_commit_command_is_a_no_op(repo, stubs):
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, {"tool_input": {"command": "git status"}}, stubs)
    assert result.returncode == 0
    assert not (stubs / "semgrep.args").exists()


def test_reachable_registry_adds_p_default_to_local_rules(repo, stubs):
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, stubs=stubs)  # curl stub answers 200
    assert result.returncode == 0, result.stderr
    args = semgrep_args(stubs)
    assert args[:2] == ["scan", "--config"]
    assert Path(args[2]).resolve() == LOCAL_RULES.resolve()
    assert args[3:5] == ["--config", "p/default"]
    assert "auto" not in args
    for flag in ("--error", "--disable-version-check"):
        assert flag in args
    assert args[args.index("--metrics") + 1] == "off"
    assert args[-1] == "app.py"
    assert "Semgrep clean (1 file(s) scanned; rules: local rules + p/default)" in result.stderr


@pytest.mark.parametrize(
    "curl_rc,http_code",
    [(56, "000"),  # proxy refused the CONNECT (Claude Code cloud sessions)
     (6, "000"),   # DNS failure (offline laptop)
     (28, "000"),  # timed out
     (0, "503"),   # server error: Semgrep would retry for ~100 s
     (0, "429")],  # rate limited: same
)
def test_unreachable_registry_scans_with_local_rules_only(repo, stubs, curl_rc, http_code):
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, stubs=stubs, STUB_CURL_RC=str(curl_rc), STUB_CURL_CODE=http_code)
    assert result.returncode == 0, result.stderr
    assert "p/default" not in semgrep_args(stubs)
    assert "rules: local rules only (semgrep.dev unreachable)" in result.stderr


def test_offline_env_skips_probe_and_registry(repo, stubs):
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, stubs=stubs, BRAIN_PRECOMMIT_OFFLINE="1")
    assert result.returncode == 0, result.stderr
    assert not (stubs / "curl.args").exists()
    assert "p/default" not in semgrep_args(stubs)
    assert "rules: local rules only (BRAIN_PRECOMMIT_OFFLINE=1)" in result.stderr


def test_commit_from_subdirectory_still_scans(repo, stubs):
    stage(repo, "pkg/app.py", "x = 1\n")
    result = run_hook(repo / "pkg", stubs=stubs)
    assert result.returncode == 0, result.stderr
    assert semgrep_args(stubs)[-1] == "pkg/app.py"


def test_staged_file_missing_from_worktree_is_skipped(repo, stubs):
    stage(repo, "app.py", "x = 1\n")
    stage(repo, "gone.py", "y = 2\n")
    (repo / "gone.py").unlink()
    result = run_hook(repo, stubs=stubs)
    assert result.returncode == 0, result.stderr
    args = semgrep_args(stubs)
    assert "app.py" in args
    assert "gone.py" not in args


# ── Reporting: findings vs. Semgrep that could not run ──────────────────────

def test_findings_block_as_policy_violations(repo, stubs):
    stage(repo, "app.py", "x = 1\n")
    report = json.dumps({"results": [{"check_id": "demo"}], "errors": []})
    result = run_hook(repo, stubs=stubs, STUB_SEMGREP_RC="1",
                      STUB_SEMGREP_JSON=report, STUB_SEMGREP_TEXT="1 Code Finding")
    assert result.returncode == 2
    assert "Semgrep found policy violations" in result.stderr
    assert "(1 finding(s);" in result.stderr
    assert "1 Code Finding" in result.stderr
    assert "could not run" not in result.stderr


@pytest.mark.parametrize("rc", [2, 4, 5, 7])
def test_semgrep_errors_block_as_could_not_run(repo, stubs, rc):
    stage(repo, "app.py", "x = 1\n")
    report = json.dumps({"results": [], "errors": [
        {"message": "unable to find a config; path `x.yml` does not exist"}]})
    result = run_hook(repo, stubs=stubs, STUB_SEMGREP_RC=str(rc), STUB_SEMGREP_JSON=report)
    assert result.returncode == 2
    assert f"Semgrep could not run (exit {rc})" in result.stderr
    assert "unable to find a config" in result.stderr
    assert "policy violations" not in result.stderr


def test_exit_1_without_findings_is_could_not_run(repo, stubs):
    # A Python crash before Semgrep's error handling also exits 1, and it
    # writes no report. That is a broken gate, not a finding.
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, stubs=stubs, STUB_SEMGREP_RC="1",
                      STUB_SEMGREP_TEXT="Traceback (most recent call last):")
    assert result.returncode == 2
    assert "Semgrep could not run (exit 1)" in result.stderr
    assert "Traceback" in result.stderr
    assert "policy violations" not in result.stderr


def test_unexpected_hook_error_blocks_instead_of_passing(repo, stubs, tmp_path):
    # mktemp fails when TMPDIR is missing. Under `set -e` that used to exit
    # 1, which Claude Code treats as non-blocking: the commit went through.
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, stubs=stubs, TMPDIR=str(tmp_path / "missing"))
    assert result.returncode == 2
    assert "hook error near line" in result.stderr
    assert not (stubs / "semgrep.args").exists()


# ── Git pre-commit stage ────────────────────────────────────────────────────

GIT_HOOKS_DIR = "scripts/hooks/git"
# Keep the developer's own git config (a global core.hooksPath, say) out.
ISOLATED_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
FINDING = json.dumps({"results": [{"check_id": "demo"}], "errors": []})


def git(repo: Path, *args: str, env: dict | None = None, check: bool = True):
    return subprocess.run(["git", *args], cwd=repo, env=env, check=check,
                          capture_output=True, text=True, timeout=120)


def stub_env(stubs: Path, **overrides: str) -> dict:
    env = {**os.environ, **ISOLATED_GIT, "STUB_DIR": str(stubs),
           "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}
    env.pop("BRAIN_PRECOMMIT_OFFLINE", None)
    env.update(overrides)
    return env


@pytest.fixture
def gated_repo(tmp_path):
    """A repo with the gate's files at their real paths and one commit."""
    path = tmp_path / "gated"
    (path / GIT_HOOKS_DIR).mkdir(parents=True)
    (path / ".semgrep").mkdir()
    shutil.copy(HOOK, path / "scripts" / "hooks" / HOOK.name)
    shutil.copy(ROOT / GIT_HOOKS_DIR / "pre-commit", path / GIT_HOOKS_DIR / "pre-commit")
    shutil.copy(LOCAL_RULES, path / ".semgrep" / "rules.yml")
    (path / "app.py").write_text("x = 1\n")
    env = {**os.environ, **ISOLATED_GIT}
    git(path, "init", "-q", env=env)
    git(path, "config", "user.email", "test@example.com", env=env)
    git(path, "config", "user.name", "test", env=env)
    git(path, "add", "-A", env=env)
    git(path, "commit", "-qm", "init", env=env)
    return path


def run_gated_hook(repo: Path, stubs: Path, payload=COMMIT, **env: str):
    return run_hook(repo, payload, stubs, hook=repo / "scripts" / "hooks" / HOOK.name,
                    **ISOLATED_GIT, **env)


def hooks_path(repo: Path) -> str:
    return git(repo, "config", "--get", "core.hooksPath", env={**os.environ, **ISOLATED_GIT},
               check=False).stdout.strip()


def test_pretooluse_arms_git_stage_and_hands_off(gated_repo, stubs):
    for _ in range(2):  # arming, then already armed
        result = run_gated_hook(gated_repo, stubs)
        assert result.returncode == 0, result.stderr
        assert "Semgrep runs inside git commit" in result.stderr
    assert hooks_path(gated_repo) == GIT_HOOKS_DIR
    assert not (stubs / "semgrep.args").exists()


@pytest.mark.parametrize("existing", ["git-hooks-file", "hooks-path"])
def test_arming_leaves_existing_hook_setups_alone(gated_repo, stubs, existing):
    stage(gated_repo, "app.py", "x = 2\n")
    if existing == "git-hooks-file":
        own_hook = gated_repo / ".git" / "hooks" / "pre-commit"
        own_hook.write_text("#!/bin/sh\nexit 0\n")
        own_hook.chmod(0o755)
        expected = ""
    else:
        git(gated_repo, "config", "core.hooksPath", "other/hooks")
        expected = "other/hooks"
    result = run_gated_hook(gated_repo, stubs)
    assert result.returncode == 0, result.stderr
    assert "not arming" in result.stderr
    assert hooks_path(gated_repo) == expected
    assert (stubs / "semgrep.args").exists()  # scanned in PreToolUse instead


def test_command_that_skips_git_hooks_is_scanned_in_pretooluse(gated_repo, stubs):
    git(gated_repo, "config", "core.hooksPath", GIT_HOOKS_DIR)
    stage(gated_repo, "app.py", "x = 2\n")
    payload = {"tool_input": {"command": "git commit --no-verify -m test"}}
    result = run_gated_hook(gated_repo, stubs, payload)
    assert result.returncode == 0, result.stderr
    assert "command skips git hooks" in result.stderr
    assert semgrep_args(stubs)[-1] == "app.py"


@pytest.mark.parametrize("how", ["commit -a", "commit <path>", "add && commit"])
def test_git_stage_blocks_findings_the_commit_command_stages(gated_repo, stubs, how):
    # Nothing is staged up front: exactly what the PreToolUse stage can't see.
    git(gated_repo, "config", "core.hooksPath", GIT_HOOKS_DIR)
    env = stub_env(stubs, STUB_SEMGREP_RC="1", STUB_SEMGREP_JSON=FINDING)
    head = git(gated_repo, "rev-parse", "HEAD").stdout
    if how == "add && commit":
        target = "new.py"
        (gated_repo / target).write_text("y = 1\n")
        git(gated_repo, "add", target, env=env)
        result = git(gated_repo, "commit", "-m", "test", env=env, check=False)
    else:
        target = "app.py"
        (gated_repo / target).write_text("x = 2\n")
        args = ["-am", "test"] if how == "commit -a" else ["-m", "test", "--", target]
        result = git(gated_repo, "commit", *args, env=env, check=False)
    assert result.returncode != 0
    assert "Semgrep found policy violations" in result.stderr
    assert semgrep_args(stubs)[-1] == target
    assert git(gated_repo, "rev-parse", "HEAD").stdout == head


def test_git_stage_lets_a_clean_commit_through(gated_repo, stubs):
    git(gated_repo, "config", "core.hooksPath", GIT_HOOKS_DIR)
    (gated_repo / "app.py").write_text("x = 2\n")
    result = git(gated_repo, "commit", "-am", "test", env=stub_env(stubs), check=False)
    assert result.returncode == 0, result.stderr
    assert "Semgrep clean (1 file(s) scanned" in result.stderr
    assert git(gated_repo, "show", "HEAD:app.py").stdout == "x = 2\n"


@real_semgrep
def test_real_semgrep_git_stage_blocks_commit_a(gated_repo):
    git(gated_repo, "config", "core.hooksPath", GIT_HOOKS_DIR)
    (gated_repo / "app.py").write_text(
        "import subprocess\n\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n")
    env = {**os.environ, **ISOLATED_GIT, "BRAIN_PRECOMMIT_OFFLINE": "1"}
    result = git(gated_repo, "commit", "-am", "test", env=env, check=False)
    assert result.returncode != 0
    assert "python-shell-injection" in result.stderr


# ── Real Semgrep, local rules, no network ───────────────────────────────────

# One snippet each rule must flag, and one it must leave alone. Credential-
# shaped strings are assembled at runtime so this file never contains one.
RULE_CASES = [
    ("python-shell-injection", "shell.py",
     "import subprocess\n\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n",
     "import subprocess\n\n\ndef run(arg):\n    subprocess.run(['ls', arg])\n"),
    ("python-eval-exec-dynamic", "dyn.py",
     "def run(code):\n    return eval(code)\n",
     "def run(model):\n    return model.eval()\n"),
    ("python-yaml-unsafe-load", "conf.py",
     "import yaml\n\n\ndef load(s):\n    return yaml.load(s, Loader=yaml.Loader)\n",
     "import yaml\n\n\ndef load(s):\n    return yaml.safe_load(s)\n"),
    ("python-tls-verification-disabled", "fetch.py",
     "import requests\n\n\ndef get(url):\n    return requests.get(url, verify=False)\n",
     "import requests\n\n\ndef get(url):\n    return requests.get(url, timeout=10)\n"),
    ("python-jwt-verification-disabled", "auth.py",
     'import jwt\n\n\ndef read(t):\n    return jwt.decode(t, options={"verify_signature": False})\n',
     'import jwt\n\n\ndef read(t, k):\n    return jwt.decode(t, k, algorithms=["HS256"])\n'),
    ("js-eval-dynamic", "page.js",
     "function run(code) { return eval(code); }\n",
     "function run(text) { return JSON.parse(text); }\n"),
    ("hardcoded-credential", "keys.py",
     'AWS_KEY = "%s"\n' % ("AKIA" + "Q" * 16),
     'import os\n\nAWS_KEY = os.environ["AWS_ACCESS_KEY_ID"]\n'),
    ("hardcoded-telegram-bot-token", "bot.sh",
     'TOKEN="%s"\n' % ("123456789:" + "A" + "b" * 34),
     'TOKEN="${TELEGRAM_BOT_TOKEN:?}"\n'),
]


@real_semgrep
def test_real_semgrep_clean_file_passes(repo):
    stage(repo, "app.py", "def add(a, b):\n    return a + b\n")
    result = run_hook(repo, BRAIN_PRECOMMIT_OFFLINE="1")
    assert result.returncode == 0, result.stderr
    assert "Semgrep clean (1 file(s) scanned" in result.stderr


@real_semgrep
def test_real_semgrep_every_local_rule_blocks_its_bad_case_only(repo):
    for _, filename, bad, _ in RULE_CASES:
        stage(repo, filename, bad)
    blocked = run_hook(repo, BRAIN_PRECOMMIT_OFFLINE="1")
    assert blocked.returncode == 2, blocked.stderr
    assert "Semgrep found policy violations" in blocked.stderr
    missing = [rule for rule, *_ in RULE_CASES if rule not in blocked.stderr]
    assert not missing, f"rules that did not fire: {missing}\n{blocked.stderr}"

    for _, filename, _, good in RULE_CASES:
        stage(repo, filename, good)
    passed = run_hook(repo, BRAIN_PRECOMMIT_OFFLINE="1")
    assert passed.returncode == 0, passed.stderr


@real_semgrep
def test_real_semgrep_broken_rules_report_could_not_run(repo, tmp_path):
    # Same hook, pointed at an unparseable rules file through the layout it
    # resolves rules from (<root>/scripts/hooks/ -> <root>/.semgrep/).
    fake_root = tmp_path / "fake-root"
    (fake_root / "scripts" / "hooks").mkdir(parents=True)
    (fake_root / ".semgrep").mkdir()
    hook = fake_root / "scripts" / "hooks" / HOOK.name
    shutil.copy(HOOK, hook)
    (fake_root / ".semgrep" / "rules.yml").write_text("rules: [\n  - id: x\n")
    stage(repo, "app.py", "x = 1\n")
    result = run_hook(repo, hook=hook, BRAIN_PRECOMMIT_OFFLINE="1")
    assert result.returncode == 2
    assert "Semgrep could not run (exit 7)" in result.stderr
    assert "Invalid YAML" in result.stderr
    assert "policy violations" not in result.stderr
