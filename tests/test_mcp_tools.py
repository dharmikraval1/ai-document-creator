import asyncio


def test_document_local_project_uses_fake_backend(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")

    import mcp_server_impl as server
    from core.backends import FakeBackend

    # Force a deterministic backend regardless of env/host.
    monkeypatch.setattr(server, "pick_backend", lambda config, ctx=None: FakeBackend(
        "### Summary\nA file.\n### Overview\nbody"
    ))

    out_dir = tmp_path / "out"
    result = asyncio.run(
        server.document_local_project(
            path=str(tmp_path),
            output_dir=str(out_dir),
            ctx=None,
        )
    )

    assert "Documentation Generation Report" in result
    assert (out_dir / "README.md").exists()
    assert (out_dir / "main.py.md").exists()


def test_document_repo_threads_github_token_and_cleans_up(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text("y = 1", encoding="utf-8")

    import mcp_server_impl as server
    from core.backends import FakeBackend

    created = {}

    class _FakeGitSource:
        def __init__(self, repo_url, github_token=None):
            created["repo_url"] = repo_url
            created["github_token"] = github_token

        def prepare(self):
            return str(tmp_path)

        def cleanup(self):
            created["cleaned"] = True

    monkeypatch.setattr(server, "GitSource", _FakeGitSource)
    monkeypatch.setattr(server, "pick_backend", lambda config, ctx=None: FakeBackend("### Summary\nok"))

    result = asyncio.run(
        server.document_repo(
            repo_url="https://github.com/u/r",
            output_dir=str(tmp_path / "out"),
            github_token="tok",
            ctx=None,
        )
    )
    assert "Documentation Generation Report" in result
    assert created["repo_url"] == "https://github.com/u/r"
    assert created["github_token"] == "tok"
    assert created["cleaned"] is True


def test_pipeline_cleans_up_source_on_failure(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text("y = 1", encoding="utf-8")

    import mcp_server_impl as server

    cleaned = {"value": False}

    class _FakeLocalSource:
        def __init__(self, path):
            self._path = path

        def prepare(self):
            return str(tmp_path)

        def cleanup(self):
            cleaned["value"] = True

    def _boom(config, ctx=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(server, "LocalSource", _FakeLocalSource)
    monkeypatch.setattr(server, "pick_backend", _boom)

    result = asyncio.run(
        server.document_local_project(path=str(tmp_path), output_dir=str(tmp_path / "o"), ctx=None)
    )
    assert "Error occurred" in result
    assert cleaned["value"] is True  # cleanup runs even when the pipeline raises


def test_document_local_project_empty_dir_returns_no_files(tmp_path):
    import mcp_server_impl as server

    empty = tmp_path / "empty"
    empty.mkdir()
    result = asyncio.run(
        server.document_local_project(path=str(empty), output_dir=str(tmp_path / "o"), ctx=None)
    )
    assert result == "No files found to document."
