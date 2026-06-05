# tests/test_graph.py
import os


async def test_pipeline_generates_docs_and_index_with_fake_backend(tmp_path):
    # arrange a tiny repo
    (tmp_path / "a.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1  # {not a format placeholder}", encoding="utf-8")

    from core.backends import FakeBackend
    from core.graph import app

    state = {
        "repo_path": str(tmp_path),
        "files": ["a.py", "b.py"],
        "documents": {},
        "index_content": "",
        "backend": FakeBackend("### Summary\nMocked summary.\n### Overview\nbody"),
        "max_concurrency": 4,
    }

    result = await app.ainvoke(state)

    assert set(result["documents"].keys()) == {"a.py", "b.py"}
    assert "Mocked summary." in result["documents"]["a.py"]
    assert result["index_content"]  # index produced from summaries


async def test_pipeline_isolates_unreadable_file(tmp_path):
    from core.backends import FakeBackend
    from core.graph import app

    state = {
        "repo_path": str(tmp_path),
        "files": ["missing.py"],
        "documents": {},
        "index_content": "",
        "backend": FakeBackend("doc"),
        "max_concurrency": 2,
    }
    result = await app.ainvoke(state)
    assert "Error reading file" in result["documents"]["missing.py"]
