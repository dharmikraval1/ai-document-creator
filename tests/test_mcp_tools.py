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
