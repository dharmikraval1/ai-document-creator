# tests/test_doc_jobs.py — host-driven documentation jobs (zero-key path)
import asyncio
import re

import ai_doc_creator.server as server
from ai_doc_creator.core.jobs import DocJob, JobError, JobStore, new_job_id


def _job_id_from(briefing: str) -> str:
    match = re.search(r"job_id\*\*: `(\w+)`", briefing)
    assert match, briefing
    return match.group(1)


def _project(tmp_path):
    (tmp_path / "config.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("import config\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text("import config\n", encoding="utf-8")
    return tmp_path


# --- full happy-path flow ------------------------------------------------------


def test_full_job_flow_local(tmp_path, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    project = _project(tmp_path)
    out = tmp_path / "out"

    briefing = asyncio.run(
        server.start_doc_job(path=str(project), output_dir=str(out), profile="architecture")
    )
    assert "Documentation Job Started" in briefing
    assert "get_next_files" in briefing
    job_id = _job_id_from(briefing)

    batch = asyncio.run(server.get_next_files(job_id, max_files=10))
    assert "## FILE: app.py" in batch and "## FILE: config.py" in batch
    assert "### Summary" in batch  # profile template included
    assert "submit_docs" in batch

    progress = asyncio.run(
        server.submit_docs(
            job_id,
            {
                "app.py": "### Summary\napp\n",
                "config.py": "### Summary\nconfig\n",
                "worker.py": "### Summary\nworker\n",
            },
        )
    )
    assert "all 3 files documented" in progress
    assert "finish_doc_job" in progress

    report = asyncio.run(
        server.finish_doc_job(job_id, index_markdown="# My Project\n\nGreat project.")
    )
    assert "Documentation Job Complete" in report
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "My Project" in readme
    assert "## Architecture Diagrams" in readme  # deterministic diagrams appended
    assert (out / "app.py.md").read_text(encoding="utf-8").startswith("### Summary")

    # job is gone after finish
    assert asyncio.run(server.get_next_files(job_id)).startswith("Error")


def test_finish_refuses_while_files_remain_and_default_index(tmp_path, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    project = _project(tmp_path)
    out = tmp_path / "out"
    job_id = _job_id_from(
        asyncio.run(server.start_doc_job(path=str(project), output_dir=str(out)))
    )

    early = asyncio.run(server.finish_doc_job(job_id))
    assert early.startswith("Error") and "still need docs" in early

    asyncio.run(server.get_next_files(job_id, max_files=10))
    asyncio.run(
        server.submit_docs(
            job_id, {f: "### Summary\nd\n" for f in ["app.py", "config.py", "worker.py"]}
        )
    )
    report = asyncio.run(server.finish_doc_job(job_id))  # no index_markdown
    assert "Documentation Job Complete" in report
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Documentation Index" in readme  # TOC fallback
    assert "[`app.py`](app.py.md)" in readme


def test_submit_rejects_unknown_paths_and_sanitizes_mermaid(tmp_path, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    project = _project(tmp_path)
    job_id = _job_id_from(asyncio.run(server.start_doc_job(path=str(project))))
    asyncio.run(server.get_next_files(job_id, max_files=10))

    bad = asyncio.run(server.submit_docs(job_id, {"nope.py": "x"}))
    assert bad.startswith("Error") and "nope.py" in bad

    asyncio.run(
        server.submit_docs(
            job_id,
            {
                "app.py": "### Summary\n```mermaid\nbroken [ block\n```\n",
                "config.py": "d",
                "worker.py": "d",
            },
        )
    )
    job = server._job_store.get(job_id)
    assert "```mermaid" not in job.docs["app.py"]
    assert "```text" in job.docs["app.py"]
    server._job_store.remove(job_id)


def test_start_requires_exactly_one_source_and_valid_profile(tmp_path):
    both = asyncio.run(
        server.start_doc_job(repo_url="https://github.com/u/r", path=str(tmp_path))
    )
    assert both.startswith("Error")
    neither = asyncio.run(server.start_doc_job())
    assert neither.startswith("Error")
    bad_profile = asyncio.run(server.start_doc_job(path=str(tmp_path), profile="banana"))
    assert bad_profile.startswith("Error") and "Valid profiles" in bad_profile


def test_remote_job_local_path_gated_and_repo_inlines(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.delenv("LOCAL_ROOT", raising=False)
    gated = asyncio.run(server.start_doc_job(path=str(tmp_path)))
    assert gated == server._LOCAL_TOOL_DISABLED_MSG

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    project = _project(proj_dir)

    class _FakeSource:
        def __init__(self, *a, **k):
            pass

        def prepare(self):
            return str(project)

        def cleanup(self):
            pass

    monkeypatch.setattr(server, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(server, "GitSource", _FakeSource)

    job_id = _job_id_from(
        asyncio.run(server.start_doc_job(repo_url="https://github.com/u/r"))
    )
    asyncio.run(server.get_next_files(job_id, max_files=10))
    asyncio.run(
        server.submit_docs(
            job_id, {f: "### Summary\nremote body\n" for f in ["app.py", "config.py", "worker.py"]}
        )
    )
    report = asyncio.run(server.finish_doc_job(job_id))
    # remote: docs come back inline by default; nothing persisted at caller paths
    assert "## Generated Documentation Files" in report
    assert "remote body" in report


def test_batching_respects_max_files(tmp_path, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    project = _project(tmp_path)
    job_id = _job_id_from(asyncio.run(server.start_doc_job(path=str(project))))
    batch = asyncio.run(server.get_next_files(job_id, max_files=1))
    assert batch.count("## FILE:") == 1
    server._job_store.remove(job_id)


# --- job store unit tests --------------------------------------------------------


class _NullSource:
    cleaned = False

    def cleanup(self):
        self.cleaned = True


def _mk_job(**kwargs):
    defaults = dict(
        job_id=new_job_id(), repo_path=".", source=_NullSource(), pending=["a.py"]
    )
    defaults.update(kwargs)
    return DocJob(**defaults)


def test_job_store_expiry_cleans_source():
    store = JobStore(max_jobs=5, ttl_s=0)
    job = _mk_job()
    store.create(job)
    try:
        store.get(job.job_id)
        assert False, "expected JobError"
    except JobError:
        pass
    assert job.source.cleaned


def test_job_store_capacity_limit():
    store = JobStore(max_jobs=1, ttl_s=1000)
    store.create(_mk_job())
    try:
        store.create(_mk_job())
        assert False, "expected JobError"
    except JobError as exc:
        assert "Too many" in str(exc)
