# tests/test_pr_push.py
import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest


def _make_gh_repo(default_branch="main", existing_files=None):
    """Return a minimal mock of a PyGithub Repository object."""
    branch_mock = MagicMock()
    branch_mock.commit.sha = "abc123"

    repo = MagicMock()
    repo.default_branch = default_branch
    repo.get_branch.return_value = branch_mock
    repo.create_git_ref.return_value = MagicMock()

    pr_mock = MagicMock()
    pr_mock.html_url = "https://github.com/user/repo/pull/1"
    repo.create_pull.return_value = pr_mock

    if existing_files:
        def _get_contents(path, ref=None):
            if path in existing_files:
                m = MagicMock()
                m.sha = "fileSHA"
                return m
            from github import GithubException
            raise GithubException(404, "not found")
        repo.get_contents.side_effect = _get_contents
    else:
        from github import GithubException
        repo.get_contents.side_effect = GithubException(404, "not found")

    return repo


def test_parse_github_slug_standard_url():
    from mcp_server_impl import _parse_github_slug
    assert _parse_github_slug("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_github_slug_with_dot_git():
    from mcp_server_impl import _parse_github_slug
    assert _parse_github_slug("https://github.com/owner/repo.git") == ("owner", "repo")


def test_parse_github_slug_invalid_url():
    from mcp_server_impl import _parse_github_slug
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_github_slug("https://gitlab.com/owner/repo")


@pytest.mark.asyncio
async def test_push_docs_pr_creates_files_and_pr(tmp_path):
    (tmp_path / "README.md").write_text("# Hello", encoding="utf-8")
    (tmp_path / "main.py.md").write_text("# main", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("not md", encoding="utf-8")

    gh_repo = _make_gh_repo()

    mock_gh = MagicMock()
    mock_gh.return_value.get_repo.return_value = gh_repo

    with patch("mcp_server_impl.Github", mock_gh):
        from mcp_server_impl import _push_docs_pr
        result = await _push_docs_pr(
            repo_url="https://github.com/user/repo",
            docs_dir=str(tmp_path),
            branch="docs/test-branch",
            title="docs: test",
            github_token="fake-token",
        )

    assert result == "https://github.com/user/repo/pull/1"
    # Only .md files committed — the .txt file must be ignored
    assert gh_repo.create_file.call_count == 2
    gh_repo.create_pull.assert_called_once_with(
        title="docs: test",
        body=(
            "Auto-generated documentation by "
            "[AI Document Creator]"
            "(https://github.com/dharmikraval1/ai-document-creator)."
        ),
        head="docs/test-branch",
        base="main",
    )


@pytest.mark.asyncio
async def test_push_docs_pr_updates_existing_files(tmp_path):
    (tmp_path / "README.md").write_text("# Updated", encoding="utf-8")

    gh_repo = _make_gh_repo(existing_files={"docs/README.md"})
    mock_gh = MagicMock()
    mock_gh.return_value.get_repo.return_value = gh_repo

    with patch("mcp_server_impl.Github", mock_gh):
        from mcp_server_impl import _push_docs_pr
        await _push_docs_pr(
            repo_url="https://github.com/user/repo",
            docs_dir=str(tmp_path),
            branch="docs/test-branch",
            title="docs: update",
            github_token="fake-token",
        )

    gh_repo.update_file.assert_called_once()
    gh_repo.create_file.assert_not_called()


@pytest.mark.asyncio
async def test_document_repo_skips_pr_when_no_token(monkeypatch):
    import mcp_server_impl as server

    async def _fake_pipeline(source, output_dir, config, ctx):
        return "# Documentation Generation Report\n\n- **Files Processed**: 1\n"

    monkeypatch.setattr(server, "validate_repo_url", lambda _u: None)
    monkeypatch.setattr(server, "_run_pipeline", _fake_pipeline)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    result = await server.document_repo(
        repo_url="https://github.com/user/repo",
        output_dir="/tmp/docs",
        github_token=None,
        push_as_pr=True,
        ctx=None,
    )

    assert "skipping PR creation" in result
