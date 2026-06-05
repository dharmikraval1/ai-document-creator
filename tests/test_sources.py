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


from core.sources import GitSource


def test_gitsource_injects_token():
    src = GitSource("https://github.com/user/repo", github_token="tok")
    assert src.repo_url == "https://tok@github.com/user/repo"
    src.cleanup()


def test_gitsource_handles_dot_git_and_existing_auth():
    a = GitSource("https://github.com/user/repo.git", github_token="tok")
    assert a.repo_url == "https://tok@github.com/user/repo.git"
    a.cleanup()
    b = GitSource("https://other@github.com/user/repo.git", github_token="new")
    assert b.repo_url == "https://other@github.com/user/repo.git"
    b.cleanup()


def test_gitsource_no_token_leaves_url_untouched():
    src = GitSource("https://github.com/user/repo.git", github_token=None)
    assert src.repo_url == "https://github.com/user/repo.git"
    src.cleanup()
