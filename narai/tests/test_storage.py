"""Tests for encrypted storage."""
import os
import pytest

os.environ.setdefault("NARAI_STORAGE_KEY", "test-key-for-pytest-only")


def test_write_read_roundtrip(tmp_path, monkeypatch):
    from narai.core import storage
    monkeypatch.setattr(storage, "_STORE_DIR", tmp_path)

    data = {"hello": "world", "n": 42, "list": [1, 2, 3]}
    storage.write("test_entry", data)
    result = storage.read("test_entry")
    assert result == data


def test_delete(tmp_path, monkeypatch):
    from narai.core import storage
    monkeypatch.setattr(storage, "_STORE_DIR", tmp_path)

    storage.write("deleteme", {"x": 1})
    storage.delete("deleteme")
    with pytest.raises(FileNotFoundError):
        storage.read("deleteme")


def test_list_keys(tmp_path, monkeypatch):
    from narai.core import storage
    monkeypatch.setattr(storage, "_STORE_DIR", tmp_path)

    storage.write("a", {})
    storage.write("b", {})
    keys = storage.list_keys()
    assert set(keys) == {"a", "b"}


def test_wrong_key_fails(tmp_path, monkeypatch):
    from cryptography.fernet import InvalidToken
    from narai.core import storage

    monkeypatch.setattr(storage, "_STORE_DIR", tmp_path)

    os.environ["NARAI_STORAGE_KEY"] = "key-one"
    storage._fernet.cache_clear() if hasattr(storage._fernet, "cache_clear") else None
    storage.write("secret", {"data": "sensitive"})

    os.environ["NARAI_STORAGE_KEY"] = "key-two"
    with pytest.raises(Exception):  # InvalidToken or similar
        storage.read("secret")
