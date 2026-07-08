# ai_doc_creator/core/diagrams.py
"""Deterministic Mermaid diagram generation + validation of LLM-drawn blocks.

The dependency and structure diagrams are produced by static analysis, never
by a model, so they are always syntactically valid. Model-drawn diagrams pass
through sanitize_mermaid_blocks(), which downgrades anything suspect to a
plain fenced block rather than letting it break the rendered page.
"""
from __future__ import annotations

import os
import re

_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([.\w]+)\s+import|import\s+([.\w]+))", re.MULTILINE
)
_JS_IMPORT = re.compile(
    r"""(?:import\s+(?:[\w{}*,\s]+\s+from\s+)?|require\(\s*|import\(\s*)['"]([^'"]+)['"]"""
)
_JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_JS_RESOLVE_SUFFIXES = ("", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                        "/index.js", "/index.ts", "/index.jsx", "/index.tsx")

# First token of a fenced block must be one of these for the block to count
# as plausibly-valid Mermaid.
_MERMAID_TYPES = (
    "graph", "flowchart", "sequencediagram", "classdiagram", "statediagram",
    "statediagram-v2", "erdiagram", "journey", "pie", "gantt", "mindmap",
)
_MERMAID_FENCE = re.compile(r"```mermaid[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# Per-file read cap for import scanning: imports live at the top of files.
_SCAN_BYTES = 65536


def _max_nodes() -> int:
    try:
        return max(2, int(os.getenv("MAX_DIAGRAM_NODES", "40")))
    except ValueError:
        return 40


def _label(text: str) -> str:
    """A node label safe inside Mermaid's ["..."] syntax."""
    return text.replace('"', "'").replace("\n", " ")


def _read_head(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(_SCAN_BYTES)
    except OSError:
        return ""


def _py_module(file_path: str) -> str:
    mod = file_path[:-3].replace("\\", "/").replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def _resolve_py_import(name: str, importer: str, module_map: dict[str, str]) -> str | None:
    """Map an import name (possibly relative) to an internal file, or None."""
    if name.startswith("."):
        level = len(name) - len(name.lstrip("."))
        pkg_parts = os.path.dirname(importer).replace("\\", "/").split("/")
        pkg_parts = [p for p in pkg_parts if p]
        if level > 1:
            pkg_parts = pkg_parts[: len(pkg_parts) - (level - 1)]
        remainder = name.lstrip(".")
        name = ".".join(pkg_parts + ([remainder] if remainder else []))
    # Longest-prefix match: "a.b.c" may refer to module a/b.py's attribute c.
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in module_map:
            return module_map[candidate]
    return None


def _resolve_js_import(spec: str, importer: str, file_set: set[str]) -> str | None:
    if not spec.startswith("."):
        return None  # external package
    base = os.path.normpath(os.path.join(os.path.dirname(importer), spec))
    base = base.replace("\\", "/")
    for suffix in _JS_RESOLVE_SUFFIXES:
        candidate = base + suffix
        if candidate in file_set:
            return candidate
    return None


def _collect_edges(files: list[str], repo_path: str) -> set[tuple[str, str]]:
    file_set = {f.replace("\\", "/") for f in files}
    module_map = {_py_module(f): f for f in file_set if f.endswith(".py")}
    edges: set[tuple[str, str]] = set()
    for f in sorted(file_set):
        content = _read_head(os.path.join(repo_path, f))
        if not content:
            continue
        if f.endswith(".py"):
            for match in _PY_IMPORT.finditer(content):
                name = match.group(1) or match.group(2)
                target = _resolve_py_import(name, f, module_map)
                if target and target != f:
                    edges.add((f, target))
        elif f.endswith(_JS_EXTENSIONS):
            for match in _JS_IMPORT.finditer(content):
                target = _resolve_js_import(match.group(1), f, file_set)
                if target and target != f:
                    edges.add((f, target))
    return edges


def build_dependency_mermaid(files: list[str], repo_path: str) -> str | None:
    """Internal-module dependency graph as a fenced Mermaid block, or None
    when there is nothing meaningful to draw."""
    edges = _collect_edges(files, repo_path)
    if len(edges) < 2:
        return None

    cap = _max_nodes()
    # Keep the most-connected nodes so the capped diagram stays informative.
    degree: dict[str, int] = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    kept = set(sorted(degree, key=lambda n: (-degree[n], n))[:cap])
    kept_edges = sorted((a, b) for a, b in edges if a in kept and b in kept)
    if len(kept_edges) < 2:
        return None
    dropped = len(degree) - len(kept)

    ids = {n: f"n{i}" for i, n in enumerate(sorted(kept))}
    lines = ["```mermaid", "graph LR"]
    lines += [f'    {ids[n]}["{_label(n)}"]' for n in sorted(kept)]
    lines += [f"    {ids[a]} --> {ids[b]}" for a, b in kept_edges]
    lines.append("```")
    if dropped > 0:
        lines.append(f"\n*…plus {dropped} more module(s) not shown (MAX_DIAGRAM_NODES).*")
    return "\n".join(lines)


def build_structure_mermaid(files: list[str]) -> str | None:
    """Directory-tree chart as a fenced Mermaid block, or None for <2 files."""
    normalized = sorted({f.replace("\\", "/") for f in files})
    if len(normalized) < 2:
        return None

    cap = _max_nodes()
    ids: dict[str, str] = {".": "n0"}
    labels: dict[str, str] = {".": "(root)"}
    edges: list[tuple[str, str]] = []
    truncated = False

    def _ensure(node: str, label: str) -> bool:
        nonlocal truncated
        if node in ids:
            return True
        if len(ids) >= cap:
            truncated = True
            return False
        ids[node] = f"n{len(ids)}"
        labels[node] = label
        return True

    for f in normalized:
        parts = f.split("/")
        parent = "."
        for depth, part in enumerate(parts):
            node = "/".join(parts[: depth + 1])
            if not _ensure(node, part):
                break
            if (parent, node) not in edges:
                edges.append((parent, node))
            parent = node

    lines = ["```mermaid", "graph TD"]
    lines += [f'    {ids[n]}["{_label(labels[n])}"]' for n in ids]
    lines += [f"    {ids[a]} --> {ids[b]}" for a, b in edges if a in ids and b in ids]
    lines.append("```")
    if truncated:
        lines.append("\n*…tree truncated (MAX_DIAGRAM_NODES).*")
    return "\n".join(lines)


def _is_plausible_mermaid(body: str) -> bool:
    stripped = body.strip()
    if not stripped:
        return False
    first_token = stripped.split()[0].lower()
    if first_token not in _MERMAID_TYPES:
        return False
    for open_ch, close_ch in ("()", "[]", "{}"):
        if stripped.count(open_ch) != stripped.count(close_ch):
            return False
    return True


def sanitize_mermaid_blocks(markdown: str) -> str:
    """Downgrade implausible ```mermaid fences to plain ```text fences.

    Model-drawn diagrams are useful but not trusted: an invalid block would
    render as a raw error box on GitHub. Content is preserved either way.
    """

    def _check(match: re.Match) -> str:
        body = match.group(1)
        if _is_plausible_mermaid(body):
            return match.group(0)
        return f"```text\n{body}```"

    return _MERMAID_FENCE.sub(_check, markdown)
