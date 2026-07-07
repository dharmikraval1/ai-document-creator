# tests/test_sources.py
import os
import socket
from unittest.mock import patch

import pytest

from ai_doc_creator.core.sources import GitSource, LocalSource, Source, mask_token


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


def test_gitsource_no_token_leaves_url_untouched(monkeypatch):
    # GitSource falls back to GITHUB_TOKEN from the environment; remove it so
    # the test asserts the no-token path regardless of where it runs.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    src = GitSource("https://github.com/user/repo.git", github_token=None)
    assert src.repo_url == "https://github.com/user/repo.git"
    src.cleanup()


def test_mask_token_userpass_double_at_and_ssh():
    # user:pass form is masked
    assert mask_token("https://user:pass@host/repo") == "https://***@host/repo"
    # only the leading credential (up to the first @) is masked; rest is preserved verbatim
    assert (
        mask_token("https://tok@evil.com@github.com/u/r.git")
        == "https://***@evil.com@github.com/u/r.git"
    )
    # SSH scp-style URLs have no '://' and are left untouched
    assert mask_token("git@github.com:user/repo.git") == "git@github.com:user/repo.git"


def test_local_source_rejects_file_path(tmp_path):
    f = tmp_path / "afile.txt"
    f.write_text("x", encoding="utf-8")
    src = LocalSource(str(f))
    with pytest.raises(FileNotFoundError):
        src.prepare()


def test_gitsource_prepare_rejects_http_url():
    src = GitSource("http://github.com/user/repo")
    with pytest.raises(ValueError, match="Only https://"):
        src.prepare()
    src.cleanup()


def test_gitsource_prepare_rejects_private_ip():
    with patch(
        "ai_doc_creator.core.guards.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))],
    ):
        src = GitSource("https://internal.corp.example/repo")
        with pytest.raises(ValueError, match="private or reserved"):
            src.prepare()
        src.cleanup()
