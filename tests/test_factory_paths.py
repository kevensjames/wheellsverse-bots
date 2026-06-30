# tests/test_factory_paths.py
import os
from pathlib import Path
from factory import paths


def test_data_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))
    assert paths.data_root() == tmp_path / "fx"


def test_data_root_default_is_repo_data_factory(monkeypatch):
    monkeypatch.delenv("FACTORY_DATA_PATH", raising=False)
    assert paths.data_root().name == "factory"
    assert paths.data_root().parent.name == "data"


def test_project_and_workspace_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))
    assert paths.project_dir("acme") == tmp_path / "acme"
    assert paths.workspaces_root() == tmp_path / "workspaces"
    assert paths.worktrees_root() == tmp_path / "worktrees"


def test_io_helpers_are_reexported():
    assert callable(paths.load_json)
    assert callable(paths.save_json_atomic)
    assert callable(paths.append_jsonl)
    assert callable(paths.read_jsonl)
