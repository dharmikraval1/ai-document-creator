# tests/test_cache.py
import os

import pytest

from core.cache import (
    MANIFEST_FILENAME,
    compute_hashes,
    filter_changed,
    hash_file,
    load_manifest,
    save_manifest,
)


def test_hash_file_is_deterministic(tmp_path):
    (tmp_path / "a.py").write_text("hello", encoding="utf-8")
    assert hash_file(str(tmp_path), "a.py") == hash_file(str(tmp_path), "a.py")


def test_hash_file_changes_with_content(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hello", encoding="utf-8")
    h1 = hash_file(str(tmp_path), "a.py")
    f.write_text("world", encoding="utf-8")
    h2 = hash_file(str(tmp_path), "a.py")
    assert h1 != h2


def test_load_manifest_returns_none_when_missing(tmp_path):
    assert load_manifest(str(tmp_path)) is None


def test_load_manifest_returns_none_on_corrupt_json(tmp_path):
    (tmp_path / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
    assert load_manifest(str(tmp_path)) is None


def test_save_and_load_manifest_roundtrip(tmp_path):
    hashes = {"a.py": "abc123", "b.py": "def456"}
    save_manifest(hashes, str(tmp_path))
    assert load_manifest(str(tmp_path)) == hashes


def test_filter_changed_all_changed_when_no_manifest(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("y", encoding="utf-8")
    changed, unchanged = filter_changed(["a.py", "b.py"], str(tmp_path), None)
    assert set(changed) == {"a.py", "b.py"}
    assert unchanged == []


def test_filter_changed_unchanged_when_hashes_match(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    manifest = compute_hashes(["a.py"], str(tmp_path))
    changed, unchanged = filter_changed(["a.py"], str(tmp_path), manifest)
    assert changed == []
    assert unchanged == ["a.py"]


def test_filter_changed_detects_modification(tmp_path):
    (tmp_path / "a.py").write_text("old", encoding="utf-8")
    manifest = compute_hashes(["a.py"], str(tmp_path))
    (tmp_path / "a.py").write_text("new", encoding="utf-8")
    changed, unchanged = filter_changed(["a.py"], str(tmp_path), manifest)
    assert changed == ["a.py"]
    assert unchanged == []


def test_filter_changed_new_file_treated_as_changed(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("y", encoding="utf-8")
    manifest = {"a.py": hash_file(str(tmp_path), "a.py")}
    changed, unchanged = filter_changed(["a.py", "b.py"], str(tmp_path), manifest)
    assert "b.py" in changed
    assert "a.py" in unchanged
