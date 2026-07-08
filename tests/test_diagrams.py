# tests/test_diagrams.py
from ai_doc_creator.core.diagrams import (
    build_dependency_mermaid,
    build_structure_mermaid,
    sanitize_mermaid_blocks,
)


def _write(tmp_path, rel, content):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return rel


# --- dependency graph ---------------------------------------------------------


def test_python_dependency_edges(tmp_path):
    files = [
        _write(tmp_path, "pkg/config.py", "X = 1\n"),
        _write(tmp_path, "pkg/backends.py", "from pkg.config import X\nimport os\n"),
        _write(tmp_path, "pkg/server.py", "import pkg.backends\nfrom pkg.config import X\n"),
    ]
    diagram = build_dependency_mermaid(files, str(tmp_path))
    assert diagram is not None
    assert diagram.startswith("```mermaid")
    assert "graph LR" in diagram
    assert '"pkg/config.py"' in diagram
    assert "-->" in diagram


def test_python_relative_imports_resolved(tmp_path):
    files = [
        _write(tmp_path, "pkg/config.py", "X = 1\n"),
        _write(tmp_path, "pkg/sub/deep.py", "from ..config import X\nfrom . import sibling\n"),
        _write(tmp_path, "pkg/sub/sibling.py", "Y = 2\n"),
        _write(tmp_path, "pkg/other.py", "from .config import X\n"),
    ]
    diagram = build_dependency_mermaid(files, str(tmp_path))
    assert diagram is not None
    assert '"pkg/sub/deep.py"' in diagram
    assert '"pkg/config.py"' in diagram


def test_js_dependency_edges(tmp_path):
    files = [
        _write(tmp_path, "src/util.js", "export const x = 1;\n"),
        _write(tmp_path, "src/a.js", "import { x } from './util';\n"),
        _write(tmp_path, "src/b.js", "const u = require('./util.js');\nimport('./a.js');\n"),
    ]
    diagram = build_dependency_mermaid(files, str(tmp_path))
    assert diagram is not None
    assert '"src/util.js"' in diagram


def test_external_imports_ignored_and_too_few_edges_returns_none(tmp_path):
    files = [
        _write(tmp_path, "a.py", "import os\nimport sys\nimport requests\n"),
        _write(tmp_path, "b.py", "import json\n"),
    ]
    assert build_dependency_mermaid(files, str(tmp_path)) is None


def test_dependency_cap_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_DIAGRAM_NODES", "4")
    files = [_write(tmp_path, "hub.py", "X = 1\n")]
    for i in range(10):
        files.append(_write(tmp_path, f"mod{i}.py", "import hub\n"))
    diagram = build_dependency_mermaid(files, str(tmp_path))
    assert diagram is not None
    node_lines = [ln for ln in diagram.splitlines() if '["' in ln]
    assert len(node_lines) <= 4
    assert "more module(s) not shown" in diagram


def test_hostile_filenames_escaped(tmp_path):
    weird = 'we"ird.py'
    files = [
        _write(tmp_path, weird, "X = 1\n"),
        _write(tmp_path, "a.py", "import hub\n"),
        _write(tmp_path, "hub.py", "X = 1\n"),
        _write(tmp_path, "b.py", "import hub\n"),
    ]
    diagram = build_dependency_mermaid(files, str(tmp_path))
    assert diagram is not None
    assert 'we"ird' not in diagram  # double quote replaced


# --- structure chart ----------------------------------------------------------


def test_structure_chart_builds_tree():
    diagram = build_structure_mermaid(["src/a.py", "src/sub/b.py", "README.md"])
    assert diagram is not None
    assert "graph TD" in diagram
    assert '"(root)"' in diagram
    assert '"src"' in diagram
    assert '"b.py"' in diagram


def test_structure_chart_none_for_single_file():
    assert build_structure_mermaid(["only.py"]) is None


def test_structure_chart_truncates(monkeypatch):
    monkeypatch.setenv("MAX_DIAGRAM_NODES", "5")
    files = [f"dir{i}/file{i}.py" for i in range(20)]
    diagram = build_structure_mermaid(files)
    assert diagram is not None
    assert "tree truncated" in diagram


# --- sanitizer ------------------------------------------------------------------


def test_valid_mermaid_kept():
    md = "Text\n```mermaid\ngraph TD\n    a[Start] --> b[End]\n```\nMore"
    assert sanitize_mermaid_blocks(md) == md


def test_invalid_type_downgraded():
    md = "```mermaid\nnot-a-diagram at all\n```"
    out = sanitize_mermaid_blocks(md)
    assert "```text" in out
    assert "```mermaid" not in out
    assert "not-a-diagram at all" in out  # content preserved


def test_unbalanced_brackets_downgraded():
    md = "```mermaid\ngraph TD\n    a[Start --> b[End]\n```"
    out = sanitize_mermaid_blocks(md)
    assert "```text" in out


def test_empty_block_downgraded_and_multiple_blocks_independent():
    md = (
        "```mermaid\n\n```\n"
        "```mermaid\nsequenceDiagram\n    A->>B: hi\n```"
    )
    out = sanitize_mermaid_blocks(md)
    assert out.count("```text") == 1
    assert "sequenceDiagram" in out
    assert out.count("```mermaid") == 1
