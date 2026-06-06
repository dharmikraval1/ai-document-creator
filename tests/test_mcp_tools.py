import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


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


# ── new tests for Task 7 hardening ───────────────────────────────────────────

async def test_health_endpoint_returns_ok():
    from mcp_server_impl import health

    class _Req:
        pass

    response = await health(_Req())
    data = json.loads(response.body)
    assert data == {"status": "ok", "version": "2.0.0"}


async def test_document_local_project_times_out(monkeypatch, tmp_path):
    import mcp_server_impl as server
    from core.config import DocConfig

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
    import mcp_server_impl as server

    def _raise(_p):
        raise ValueError("outside LOCAL_ROOT")

    monkeypatch.setattr(server, "validate_local_path", _raise)
    result = await server.document_local_project(path="/etc", ctx=None)
    assert "Error:" in result
    assert "outside" in result


async def test_document_repo_rejects_http_url():
    import mcp_server_impl as server

    result = await server.document_repo(repo_url="http://github.com/user/repo", ctx=None)
    assert "Error:" in result
    assert "https" in result
