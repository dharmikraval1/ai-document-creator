# tests/test_graph.py


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


async def test_generate_docs_respects_concurrency_limit(tmp_path):
    import asyncio

    from core.backends import CompletionBackend
    from core.graph import app

    for i in range(10):
        (tmp_path / f"f{i}.py").write_text(f"x = {i}", encoding="utf-8")

    class _CountingBackend(CompletionBackend):
        def __init__(self):
            self.inflight = 0
            self.max_inflight = 0

        async def complete(self, prompt):
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            await asyncio.sleep(0.01)
            self.inflight -= 1
            return "### Summary\nok"

    backend = _CountingBackend()
    state = {
        "repo_path": str(tmp_path),
        "files": [f"f{i}.py" for i in range(10)],
        "documents": {},
        "index_content": "",
        "backend": backend,
        "max_concurrency": 3,
    }
    await app.ainvoke(state)
    assert backend.max_inflight <= 3  # the semaphore bound is respected
    assert backend.max_inflight >= 2  # and work actually ran concurrently (not serialized)


async def test_backend_exception_is_isolated_per_file(tmp_path):
    from core.backends import CompletionBackend
    from core.graph import app

    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")

    class _SelectiveBackend(CompletionBackend):
        # Fail per-file doc generation but let the index call succeed,
        # so we can assert the per-file error is captured (not aborting the run).
        async def complete(self, prompt):
            if "README.md" in prompt:
                return "INDEX OK"
            raise RuntimeError("boom")

    state = {
        "repo_path": str(tmp_path),
        "files": ["a.py"],
        "documents": {},
        "index_content": "",
        "backend": _SelectiveBackend(),
        "max_concurrency": 2,
    }
    result = await app.ainvoke(state)
    assert "Error generating documentation: boom" in result["documents"]["a.py"]
    assert result["index_content"] == "INDEX OK"


def test_extract_summary_keeps_inline_hashes():
    from core.graph import _extract_summary

    doc = "### Summary\nLine one ### inline marker\nmore\n## Overview\nx"
    assert _extract_summary(doc) == "Line one ### inline marker\nmore"
