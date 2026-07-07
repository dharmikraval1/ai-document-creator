# tests/test_phase4_server.py — BYOK headers, remote-mode gating, return_docs, transports
import asyncio
from unittest.mock import MagicMock

import ai_doc_creator.server as server
from ai_doc_creator.core.backends import FakeBackend
from ai_doc_creator.core.config import DocConfig


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


class _FakeCtx:
    """Mimics FastMCP Context enough for header extraction."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.request_context = MagicMock()
        self.request_context.request = _FakeRequest(headers or {})


# --- header extraction / request config -------------------------------------


def test_request_headers_empty_on_stdio():
    assert server._request_headers(None) == {}
    ctx = MagicMock()
    ctx.request_context = property(lambda self: (_ for _ in ()).throw(ValueError()))
    no_req = _FakeCtx()
    no_req.request_context.request = None
    assert server._request_headers(no_req) == {}


def test_header_key_sets_api_key_and_default_provider():
    ctx = _FakeCtx({"X-Provider-API-Key": "sk-user-123"})
    config = server._resolve_request_config(None, None, True, ctx)
    assert isinstance(config, DocConfig)
    assert config.api_key == "sk-user-123"
    assert config.provider == "anthropic"


def test_header_provider_and_model_used_when_args_absent():
    ctx = _FakeCtx(
        {
            "X-Provider-API-Key": "sk-u",
            "X-Provider": "openai",
            "X-Model": "gpt-4o-mini",
        }
    )
    config = server._resolve_request_config(None, None, True, ctx)
    assert (config.provider, config.model) == ("openai", "gpt-4o-mini")


def test_tool_args_win_over_headers():
    ctx = _FakeCtx({"X-Provider-API-Key": "sk-u", "X-Provider": "openai", "X-Model": "m1"})
    config = server._resolve_request_config("anthropic", "m2", True, ctx)
    assert (config.provider, config.model) == ("anthropic", "m2")
    assert config.api_key == "sk-u"


def test_header_key_with_unsupported_provider_is_an_error():
    ctx = _FakeCtx({"X-Provider-API-Key": "sk-u", "X-Provider": "bedrock"})
    result = server._resolve_request_config(None, None, True, ctx)
    assert isinstance(result, str) and result.startswith("Error")


def test_api_key_never_appears_in_config_repr():
    config = DocConfig(provider="anthropic", api_key="sk-secret-xyz")
    assert "sk-secret-xyz" not in repr(config)
    assert "sk-secret-xyz" not in str(config)


# --- BYOK_ONLY semantics ------------------------------------------------------


def _fake_project(tmp_path):
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")
    return tmp_path


def test_byok_only_drops_env_provider_without_request_key(tmp_path, monkeypatch):
    _fake_project(tmp_path)
    seen: list[DocConfig] = []

    def fake_pick(config, ctx=None):
        seen.append(config)
        return FakeBackend("### Summary\nx\n### Overview\ny")

    monkeypatch.setattr(server, "pick_backend", fake_pick)
    monkeypatch.setattr(server, "_BYOK_ONLY", True)

    result = asyncio.run(
        server.document_local_project(
            path=str(tmp_path), output_dir=str(tmp_path / "out"), provider="anthropic", ctx=None
        )
    )
    assert "Documentation Generation Report" in result
    assert seen[0].provider is None  # env/server credentials never used
    assert seen[0].api_key is None


def test_byok_only_keeps_per_request_key(tmp_path, monkeypatch):
    _fake_project(tmp_path)
    seen: list[DocConfig] = []

    def fake_pick(config, ctx=None):
        seen.append(config)
        return FakeBackend("### Summary\nx\n### Overview\ny")

    monkeypatch.setattr(server, "pick_backend", fake_pick)
    monkeypatch.setattr(server, "_BYOK_ONLY", True)

    ctx = _FakeCtx({"X-Provider-API-Key": "sk-user", "X-Provider": "openai"})
    result = asyncio.run(
        server.document_local_project(
            path=str(tmp_path), output_dir=str(tmp_path / "out"), ctx=ctx
        )
    )
    assert "Documentation Generation Report" in result
    assert seen[0].provider == "openai"
    assert seen[0].api_key == "sk-user"


# --- remote-mode gating -------------------------------------------------------


def test_local_tools_disabled_when_remote(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.delenv("LOCAL_ROOT", raising=False)
    r1 = asyncio.run(server.document_local_project(path=str(tmp_path)))
    r2 = asyncio.run(server.check_doc_drift(path=str(tmp_path)))
    assert r1 == server._LOCAL_TOOL_DISABLED_MSG
    assert r2 == server._LOCAL_TOOL_DISABLED_MSG


def test_local_tool_allowed_remotely_with_local_root(tmp_path, monkeypatch):
    _fake_project(tmp_path)
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    monkeypatch.setattr(
        server,
        "pick_backend",
        lambda config, ctx=None: FakeBackend("### Summary\nx\n### Overview\ny"),
    )
    result = asyncio.run(
        server.document_local_project(path=str(tmp_path), output_dir=str(tmp_path / "out"))
    )
    assert "Documentation Generation Report" in result


class _FakeSource:
    """Stands in for GitSource: serves a prepared directory, records cleanup."""

    prepared_dirs: list[str] = []

    def __init__(self, path):
        self._path = str(path)

    def prepare(self):
        return self._path

    def cleanup(self):
        pass


def test_document_repo_remote_ignores_output_dir_and_inlines_docs(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text("print('x')", encoding="utf-8")

    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setattr(server, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(server, "GitSource", lambda url, github_token=None, use_env_token=True: _FakeSource(project))
    monkeypatch.setattr(
        server,
        "pick_backend",
        lambda config, ctx=None: FakeBackend("### Summary\nremote doc\n### Overview\nbody"),
    )

    caller_output = tmp_path / "attacker-chosen-dir"
    result = asyncio.run(
        server.document_repo(
            repo_url="https://github.com/u/r",
            output_dir=str(caller_output),
            return_docs=True,
        )
    )
    assert "Documentation Generation Report" in result
    assert not caller_output.exists()  # caller's server path never written
    assert "## Generated Documentation Files" in result
    assert "remote doc" in result


def test_document_repo_local_still_honors_output_dir(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text("print('x')", encoding="utf-8")

    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(server, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(server, "GitSource", lambda url, github_token=None, use_env_token=True: _FakeSource(project))
    monkeypatch.setattr(
        server,
        "pick_backend",
        lambda config, ctx=None: FakeBackend("### Summary\nx\n### Overview\ny"),
    )

    out = tmp_path / "docs-out"
    result = asyncio.run(
        server.document_repo(repo_url="https://github.com/u/r", output_dir=str(out))
    )
    assert "Documentation Generation Report" in result
    assert (out / "app.py.md").exists()


# --- inline docs cap ----------------------------------------------------------


def test_inline_docs_cap_omits_oversized_files(tmp_path, monkeypatch):
    (tmp_path / "small.md").write_text("tiny", encoding="utf-8")
    (tmp_path / "huge.md").write_text("x" * 500_000, encoding="utf-8")
    monkeypatch.setenv("MAX_INLINE_DOC_KB", "10")
    section = server._inline_docs_section(str(tmp_path))
    assert "small.md" in section
    assert "x" * 1000 not in section
    assert "omitted" in section


# --- HTTP app composition -----------------------------------------------------


def _route_paths(app):
    return {getattr(r, "path", None) for r in app.routes}


def test_build_http_app_both_serves_streamable_and_sse():
    paths = _route_paths(server.build_http_app("both"))
    assert "/mcp" in paths
    assert "/sse" in paths
    assert "/health" in paths


def test_build_http_app_single_transports():
    assert "/sse" not in _route_paths(server.build_http_app("streamable-http"))
    sse_paths = _route_paths(server.build_http_app("sse"))
    assert "/sse" in sse_paths and "/mcp" not in sse_paths


def test_remote_push_as_pr_never_uses_server_github_token(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text("print('x')", encoding="utf-8")

    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("GITHUB_TOKEN", "server-secret-token")
    monkeypatch.setattr(server, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(
        server, "GitSource", lambda url, github_token=None, use_env_token=True: _FakeSource(project)
    )
    monkeypatch.setattr(
        server,
        "pick_backend",
        lambda config, ctx=None: FakeBackend("### Summary\nx\n### Overview\ny"),
    )
    pushed = []

    async def fake_push(**kwargs):
        pushed.append(kwargs)
        return "http://pr"

    monkeypatch.setattr(server, "_push_docs_pr", fake_push)

    result = asyncio.run(
        server.document_repo(repo_url="https://github.com/u/r", push_as_pr=True)
    )
    assert pushed == []  # server token must not be spent for remote callers
    assert "no GitHub token" in result


def test_local_tool_output_dir_sandboxed(tmp_path, monkeypatch):
    _fake_project(tmp_path)
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    result = asyncio.run(
        server.document_local_project(path=str(tmp_path), output_dir="/etc/evil-docs")
    )
    assert result.startswith("Error") and "LOCAL_ROOT" in result


def test_render_hostname_auto_allowed(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "myapp.onrender.com")
    assert "myapp.onrender.com" in server._parse_allowed_hosts()
