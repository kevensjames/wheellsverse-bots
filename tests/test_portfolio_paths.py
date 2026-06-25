import json
from pathlib import Path
from core.portfolio import paths


def test_data_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert paths.data_root() == tmp_path
    assert paths.business_dir("n8n") == tmp_path / "n8n"


def test_load_json_returns_default_when_missing(tmp_path):
    assert paths.load_json(tmp_path / "nope.json", {"a": 1}) == {"a": 1}


def test_save_json_atomic_roundtrip_and_no_tmp_left(tmp_path):
    target = tmp_path / "sub" / "x.json"
    paths.save_json_atomic(target, {"hello": "world"})
    assert json.loads(target.read_text()) == {"hello": "world"}
    assert not (tmp_path / "sub" / "x.json.tmp").exists()


def test_jsonl_append_and_read(tmp_path):
    log = tmp_path / "audit.jsonl"
    paths.append_jsonl(log, {"n": 1})
    paths.append_jsonl(log, {"n": 2})
    assert paths.read_jsonl(log) == [{"n": 1}, {"n": 2}]


def test_load_json_survives_corrupt_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert paths.load_json(bad, []) == []


def test_jsonl_roundtrips_non_ascii(tmp_path):
    log = tmp_path / "audit.jsonl"
    paths.append_jsonl(log, {"msg": "café ☕ — déjà vu"})
    assert paths.read_jsonl(log) == [{"msg": "café ☕ — déjà vu"}]
