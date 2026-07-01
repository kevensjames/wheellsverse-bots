import shutil
import subprocess
from pathlib import Path

import pytest
from factory import gates


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True, check=True)
    return tmp_path


def test_run_build_passes_on_green_tests(tmp_path):
    wt = _init_repo(tmp_path)
    (wt / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n")
    res = gates.run_build(wt)
    assert res.ok is True


def test_run_build_fails_on_red_tests(tmp_path):
    wt = _init_repo(tmp_path)
    (wt / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n")
    res = gates.run_build(wt)
    assert res.ok is False


def test_run_build_custom_cmd(tmp_path):
    wt = _init_repo(tmp_path)
    assert gates.run_build(wt, cmd="python -c \"exit(0)\"").ok is True
    assert gates.run_build(wt, cmd="python -c \"exit(3)\"").ok is False


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_run_security_clean(tmp_path):
    wt = _init_repo(tmp_path)
    (wt / "app.py").write_text("x = 1\n")
    res = gates.run_security(wt)
    assert res.ok is True and res.findings == 0


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_run_security_flags_planted_secret(tmp_path):
    wt = _init_repo(tmp_path)
    # a high-entropy value gitleaks reliably detects via generic-api-key rule
    (wt / "leak.py").write_text(
        'aws_secret_access_key = "k3n29cXx9b1ZQm7U+mLwNr6yT4oKhDf8JsVpAeRi"\n'
    )
    res = gates.run_security(wt)
    assert res.ok is False and res.findings >= 1


def test_run_security_fail_closed_when_gitleaks_missing(tmp_path, monkeypatch):
    # force the binary lookup to fail -> fail closed
    monkeypatch.setattr(gates.shutil, "which", lambda _n: None)
    res = gates.run_security(_init_repo(tmp_path))
    assert res.ok is False
