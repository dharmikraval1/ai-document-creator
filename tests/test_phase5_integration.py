# tests/test_phase5_integration.py — profiles + diagrams through the real pipeline
import asyncio

import ai_doc_creator.server as server
from ai_doc_creator.core.backends import FakeBackend


def test_pipeline_appends_diagrams_and_sanitizes_bad_mermaid(tmp_path, monkeypatch):
    # A small project with a real internal dependency so the dependency
    # diagram has something to draw.
    (tmp_path / "config.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("import config\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text("import config\n", encoding="utf-8")

    # Backend emits an INVALID mermaid block — it must be downgraded, never shipped.
    monkeypatch.setattr(
        server,
        "pick_backend",
        lambda config, ctx=None: FakeBackend(
            "### Summary\nA file.\n### Diagram\n```mermaid\nbroken [ diagram\n```\n"
        ),
    )

    out = tmp_path / "out"
    result = asyncio.run(
        server.document_local_project(
            path=str(tmp_path), output_dir=str(out), profile="architecture", ctx=None
        )
    )
    assert "Documentation Generation Report" in result

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "## Architecture Diagrams" in readme
    assert "### Project Structure" in readme
    assert "### Module Dependencies" in readme

    per_file = (out / "app.py.md").read_text(encoding="utf-8")
    assert "```mermaid" not in per_file  # invalid block downgraded
    assert "```text" in per_file


def test_diagrams_false_omits_diagram_section(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("import b\n", encoding="utf-8")
    monkeypatch.setattr(
        server,
        "pick_backend",
        lambda config, ctx=None: FakeBackend("### Summary\nx\n### Overview\ny"),
    )
    out = tmp_path / "out"
    result = asyncio.run(
        server.document_local_project(
            path=str(tmp_path), output_dir=str(out), diagrams=False, ctx=None
        )
    )
    assert "Documentation Generation Report" in result
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "## Architecture Diagrams" not in readme


def test_unknown_profile_returns_clear_error(tmp_path):
    result = asyncio.run(
        server.document_local_project(path=str(tmp_path), profile="banana", ctx=None)
    )
    assert result.startswith("Error") and "Valid profiles" in result

    result2 = asyncio.run(
        server.document_repo(repo_url="https://github.com/u/r", profile="banana", ctx=None)
    )
    assert result2.startswith("Error") and "Valid profiles" in result2


def test_profile_threaded_into_prompts(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")
    backend = FakeBackend("### Summary\nx\n")
    monkeypatch.setattr(server, "pick_backend", lambda config, ctx=None: backend)

    asyncio.run(
        server.document_local_project(
            path=str(tmp_path), output_dir=str(tmp_path / "out"), profile="api", ctx=None
        )
    )
    file_prompts = [p for p in backend.calls if "File Path:" in p]
    index_prompts = [p for p in backend.calls if "Repository Structure" in p]
    assert file_prompts and "API Reference" in file_prompts[0]
    assert index_prompts and "API reference index" in index_prompts[0]
