import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


def test_document_local_project_uses_fake_backend(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")

    import ai_doc_creator.server as server
    from ai_doc_creator.core.backends import FakeBackend

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

    import ai_doc_creator.server as server
    from ai_doc_creator.core.backends import FakeBackend

    created = {}

    class _FakeGitSource:
        def __init__(self, repo_url, github_token=None, use_env_token=True):
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

    import ai_doc_creator.server as server

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
    import ai_doc_creator.server as server

    empty = tmp_path / "empty"
    empty.mkdir()
    result = asyncio.run(
        server.document_local_project(path=str(empty), output_dir=str(tmp_path / "o"), ctx=None)
    )
    assert result == "No files found to document."


# ── new tests for Task 7 hardening ───────────────────────────────────────────

async def test_health_endpoint_returns_ok():
    from ai_doc_creator.server import health

    class _Req:
        pass

    response = await health(_Req())
    data = json.loads(response.body)
    assert data == {"status": "ok", "version": "2.2.0"}


async def test_document_local_project_times_out(monkeypatch, tmp_path):
    import ai_doc_creator.server as server
    from ai_doc_creator.core.config import DocConfig

    async def _slow(*_a, **_kw):
        await asyncio.sleep(999)
        return "never"

    monkeypatch.setattr(server, "_run_pipeline", _slow)
    monkeypatch.setattr(server, "validate_local_path", lambda _p: None)
    monkeypatch.setattr(
        server, "resolve_config", lambda **_kw: DocConfig(pipeline_timeout_s=1)
    )

    result = await server.document_local_project(path=str(tmp_path), ctx=None)
    assert "timed out" in result


async def test_document_local_project_rejects_bad_path(monkeypatch):
    import ai_doc_creator.server as server

    def _raise(_p):
        raise ValueError("outside LOCAL_ROOT")

    monkeypatch.setattr(server, "validate_local_path", _raise)
    result = await server.document_local_project(path="/etc", ctx=None)
    assert "Error:" in result
    assert "outside" in result


async def test_document_repo_rejects_http_url():
    import ai_doc_creator.server as server

    result = await server.document_repo(repo_url="http://github.com/user/repo", ctx=None)
    assert "Error:" in result
    assert "https" in result


# ── incremental caching tests (Task 2) ───────────────────────────────────────

async def test_run_pipeline_returns_uptodate_when_all_unchanged(tmp_path):
    from ai_doc_creator.server import _run_pipeline
    from ai_doc_creator.core.config import DocConfig

    source = MagicMock()
    source.prepare.return_value = str(tmp_path)
    source.cleanup = MagicMock()

    config = DocConfig(incremental=True)

    with (
        patch("ai_doc_creator.server.FileTraverser") as mock_ft,
        patch("ai_doc_creator.server.load_manifest", return_value={"a.py": "abc123"}),
        patch("ai_doc_creator.server.filter_changed", return_value=([], ["a.py"])),
        patch("ai_doc_creator.server.workflow_app") as mock_app,
    ):
        mock_ft.return_value.traverse.return_value = ["a.py"]
        result = await _run_pipeline(source, str(tmp_path / "docs"), config, None)

    assert "Up to Date" in result
    mock_app.ainvoke.assert_not_called()
    source.cleanup.assert_called_once()


async def test_run_pipeline_only_invokes_changed_files(tmp_path):
    from ai_doc_creator.server import _run_pipeline
    from ai_doc_creator.core.config import DocConfig

    source = MagicMock()
    source.prepare.return_value = str(tmp_path)
    source.cleanup = MagicMock()

    config = DocConfig(incremental=True)

    fake_state = {"documents": {"changed.py": "# doc"}, "index_content": "index"}
    fake_idx = {"index_content": "merged index"}

    with (
        patch("ai_doc_creator.server.FileTraverser") as mock_ft,
        patch("ai_doc_creator.server.load_manifest", return_value={"unchanged.py": "hash1"}),
        patch("ai_doc_creator.server.filter_changed", return_value=(["changed.py"], ["unchanged.py"])),
        patch("ai_doc_creator.server.workflow_app") as mock_app,
        patch("ai_doc_creator.server._generate_index", new_callable=AsyncMock, return_value=fake_idx),
        patch("ai_doc_creator.server._load_existing_doc", return_value="# existing doc"),
        patch("ai_doc_creator.server.pick_backend", return_value=MagicMock()),
        patch("ai_doc_creator.server.DocumentationWriter") as mock_dw,
        patch("ai_doc_creator.server.compute_hashes", return_value={"changed.py": "h1", "unchanged.py": "hash1"}),
        patch("ai_doc_creator.server.save_manifest"),
    ):
        mock_ft.return_value.traverse.return_value = ["changed.py", "unchanged.py"]
        mock_app.ainvoke = AsyncMock(return_value=fake_state)
        mock_dw.return_value.write_docs = MagicMock()

        result = await _run_pipeline(source, str(tmp_path / "docs"), config, None)

    # ainvoke called with only changed files
    call_args = mock_app.ainvoke.call_args[0][0]
    assert call_args["files"] == ["changed.py"]
    assert "Documentation Generation Report" in result
    source.cleanup.assert_called_once()


async def test_run_pipeline_saves_manifest_after_run(tmp_path):
    from ai_doc_creator.server import _run_pipeline
    from ai_doc_creator.core.config import DocConfig

    source = MagicMock()
    source.prepare.return_value = str(tmp_path)
    source.cleanup = MagicMock()

    config = DocConfig(incremental=False)

    fake_state = {"documents": {"main.py": "# doc"}, "index_content": "index"}
    fake_hashes = {"main.py": "deadbeef"}

    with (
        patch("ai_doc_creator.server.FileTraverser") as mock_ft,
        patch("ai_doc_creator.server.workflow_app") as mock_app,
        patch("ai_doc_creator.server.pick_backend", return_value=MagicMock()),
        patch("ai_doc_creator.server.DocumentationWriter") as mock_dw,
        patch("ai_doc_creator.server.compute_hashes", return_value=fake_hashes),
        patch("ai_doc_creator.server.save_manifest") as mock_save,
    ):
        mock_ft.return_value.traverse.return_value = ["main.py"]
        mock_app.ainvoke = AsyncMock(return_value=fake_state)
        mock_dw.return_value.write_docs = MagicMock()

        await _run_pipeline(source, str(tmp_path / "docs"), config, None)

    mock_save.assert_called_once()
    saved_hashes, saved_dir = mock_save.call_args[0]
    assert saved_hashes == fake_hashes
    source.cleanup.assert_called_once()


# ── check_doc_drift tests (Task 3) ───────────────────────────────────────────

async def test_check_doc_drift_no_manifest(tmp_path):
    from ai_doc_creator.server import check_doc_drift
    with (
        patch("ai_doc_creator.server.validate_local_path"),
        patch("ai_doc_creator.server.load_manifest", return_value=None),
    ):
        result = await check_doc_drift(path=str(tmp_path), output_dir=str(tmp_path / "docs"))
    assert "No manifest found" in result


async def test_check_doc_drift_all_uptodate(tmp_path):
    from ai_doc_creator.server import check_doc_drift
    manifest = {"a.py": "hash1", "b.py": "hash2"}
    with (
        patch("ai_doc_creator.server.validate_local_path"),
        patch("ai_doc_creator.server.load_manifest", return_value=manifest),
        patch("ai_doc_creator.server.FileTraverser") as mock_ft,
        patch("ai_doc_creator.server.filter_changed", return_value=([], ["a.py", "b.py"])),
    ):
        mock_ft.return_value.traverse.return_value = ["a.py", "b.py"]
        result = await check_doc_drift(path=str(tmp_path), output_dir=str(tmp_path / "docs"))
    assert "up to date" in result.lower()


async def test_check_doc_drift_reports_modified(tmp_path):
    from ai_doc_creator.server import check_doc_drift
    manifest = {"a.py": "oldhash", "b.py": "hash2"}
    with (
        patch("ai_doc_creator.server.validate_local_path"),
        patch("ai_doc_creator.server.load_manifest", return_value=manifest),
        patch("ai_doc_creator.server.FileTraverser") as mock_ft,
        patch("ai_doc_creator.server.filter_changed", return_value=(["a.py"], ["b.py"])),
    ):
        mock_ft.return_value.traverse.return_value = ["a.py", "b.py"]
        result = await check_doc_drift(path=str(tmp_path), output_dir=str(tmp_path / "docs"))
    assert "Modified" in result
    assert "a.py" in result


async def test_check_doc_drift_reports_new_and_deleted(tmp_path):
    from ai_doc_creator.server import check_doc_drift
    # manifest has old.py (now deleted), new.py is new
    manifest = {"old.py": "hash_old"}
    with (
        patch("ai_doc_creator.server.validate_local_path"),
        patch("ai_doc_creator.server.load_manifest", return_value=manifest),
        patch("ai_doc_creator.server.FileTraverser") as mock_ft,
        patch("ai_doc_creator.server.filter_changed", return_value=(["new.py"], [])),
    ):
        mock_ft.return_value.traverse.return_value = ["new.py"]
        result = await check_doc_drift(path=str(tmp_path), output_dir=str(tmp_path / "docs"))
    assert "New Files" in result
    assert "new.py" in result
    assert "Deleted" in result
    assert "old.py" in result
