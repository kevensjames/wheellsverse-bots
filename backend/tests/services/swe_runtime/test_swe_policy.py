"""SWE-runtime policy, lockdown-flag construction, and flag gating (no container)."""
import pytest

from app.services.swe_runtime import config, policy
from app.services.swe_runtime.config import SandboxPolicy
from app.services.swe_runtime.sandbox import (DisabledSandbox, DockerSandbox,
                                              build_create_args, get_backend)


def test_build_create_args_has_full_lockdown():
    joined = " ".join(build_create_args("echo hi", SandboxPolicy()))
    for flag in ["--network none", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--pids-limit", "--memory", "--cpus", "--pull never"]:
        assert flag in joined, f"missing lockdown flag: {flag}"
    # no host bind mount, no docker socket exposure
    assert "-v " not in joined
    assert "docker.sock" not in joined


def test_policy_denies_egress_and_credential_commands():
    p = SandboxPolicy()
    for bad in ["curl http://x", "wget http://x", "cat ~/.ssh/id_rsa", "ssh host", "cat /etc/shadow"]:
        with pytest.raises(policy.PolicyDenied):
            policy.validate(bad, p)


def test_policy_allows_ordinary_command():
    policy.validate("python -m pytest -q && sed -i s/a/b/ lib.py", SandboxPolicy())


def test_policy_denies_disallowed_image():
    p = SandboxPolicy()
    p.image = "evil:latest"
    with pytest.raises(policy.PolicyDenied):
        policy.validate("echo hi", p)


def test_image_allowlist_default(monkeypatch):
    monkeypatch.delenv("KAI_SWE_IMAGE_ALLOWLIST", raising=False)
    assert config.image_allowed("python:3.11-slim")
    assert not config.image_allowed("ubuntu:latest")


def test_repo_allowlist_deny_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("KAI_SWE_REPO_ALLOWLIST", raising=False)
    assert config.repo_allowed(str(tmp_path)) is False


def test_repo_allowlist_allows_only_under_root(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setenv("KAI_SWE_REPO_ALLOWLIST", str(root))
    sub = root / "proj"
    sub.mkdir()
    assert config.repo_allowed(str(sub)) is True
    assert config.repo_allowed(str(tmp_path)) is False  # parent is outside the root


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KAI_SWE_RUNTIME_ENABLED", raising=False)
    backend = get_backend()
    assert isinstance(backend, DisabledSandbox)
    res = backend.run(source_dir="/x", command="echo hi", policy=SandboxPolicy())
    assert res.disabled is True and res.exit_code == -1


def test_enabled_selects_docker(monkeypatch):
    monkeypatch.setenv("KAI_SWE_RUNTIME_ENABLED", "1")
    assert isinstance(get_backend(), DockerSandbox)
