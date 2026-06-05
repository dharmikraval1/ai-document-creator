# tests/test_sources.py
import os

import pytest

from core.sources import LocalSource, Source, mask_token


def test_mask_token_hides_credentials():
    assert mask_token("https://ghp_secret@github.com/u/r.git") == "https://***@github.com/u/r.git"
    assert mask_token("https://github.com/u/r.git") == "https://github.com/u/r.git"


def test_local_source_returns_existing_dir(tmp_path):
    src = LocalSource(str(tmp_path))
    assert src.prepare() == os.path.abspath(str(tmp_path))
    src.cleanup()  # must not raise


def test_local_source_rejects_missing_dir(tmp_path):
    src = LocalSource(str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError):
        src.prepare()


def test_local_source_is_a_source():
    assert isinstance(LocalSource("."), Source)
