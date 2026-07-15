# core/graph.py
from __future__ import annotations

import asyncio
import os
import re
from typing import Dict, List, TypedDict

from langgraph.graph import END, StateGraph

from .backends import CompletionBackend
from .diagrams import (
    build_dependency_mermaid,
    build_structure_mermaid,
    sanitize_mermaid_blocks,
)
from .profiles import get_profile


class AgentState(TypedDict, total=False):
    repo_path: str
    files: List[str]
    documents: Dict[str, str]
    index_content: str
    backend: CompletionBackend
    max_concurrency: int
    profile: str
    diagrams: bool


_FILE_DIAGRAM_HINT = (
    "### Diagram\nOnly if the file has non-trivial control flow or component "
    "interactions: a small Mermaid flowchart (```mermaid fenced block, 'graph TD', "
    "under 15 nodes). Omit this section entirely for simple files.\n"
)


def build_doc_prompt(
    file_path: str,
    code_content: str,
    profile: str = "readme",
    diagrams: bool = True,
) -> str:
    prof = get_profile(profile)
    sections = prof.file_sections
    if diagrams and prof.file_diagram:
        sections += _FILE_DIAGRAM_HINT
    # f-strings avoid str.format brace issues when code contains { }.
    return (
        "You are an expert technical writer. Generate comprehensive documentation "
        "for the following code file.\n\n"
        f"File Path: {file_path}\n\n"
        "Code Content:\n"
        f"{code_content}\n\n"
        "Output Format: Markdown\n\n"
        "Include these sections:\n"
        f"{sections}"
    )


def build_index_prompt(
    file_list: str, doc_summaries: str, profile: str = "readme"
) -> str:
    prof = get_profile(profile)
    return (
        "You are an expert technical writer. Generate a premium, comprehensive README.md "
        "for the following repository.\n\n"
        f"Repository Structure (Files):\n{file_list}\n\n"
        f"Generated Documentation Summaries:\n{doc_summaries}\n\n"
        "Output Format: Markdown\n\n"
        f"{prof.index_sections}\n"
        "Do not draw a file-tree or dependency diagram — accurate diagrams are "
        "appended automatically after your output."
    )


def build_diagram_section(files: List[str], repo_path: str) -> str:
    """Deterministic Mermaid diagrams appended to the README by code, not the model."""
    parts: List[str] = []
    structure = build_structure_mermaid(files)
    if structure:
        parts.append("### Project Structure\n\n" + structure)
    dependencies = build_dependency_mermaid(files, repo_path)
    if dependencies:
        parts.append("### Module Dependencies\n\n" + dependencies)
    if not parts:
        return ""
    return (
        "\n\n## Architecture Diagrams\n\n"
        + "\n\n".join(parts)
        + "\n\n> Diagrams render on GitHub/GitLab and in IDE markdown previews; "
        "plain terminals show them as Mermaid source.\n"
    )


def _extract_summary(doc_content: str) -> str:
    match = re.search(
        r"###\s*Summary\b[ \t]*\n?([\s\S]*?)(?=^\s{0,3}#{1,6}\s|\Z)",
        doc_content,
        re.IGNORECASE | re.MULTILINE,
    )
    if match and match.group(1).strip():
        return match.group(1).strip()
    cleaned = re.sub(r"#+\s+.*", "", doc_content).strip()
    cleaned = "\n".join(line for line in cleaned.splitlines() if line.strip())
    return cleaned[:200] + "..." if len(cleaned) > 200 else cleaned


async def analyze_repo(state: AgentState):
    """Reserved entry-point seam for later phases (drift / incremental / diagrams)."""
    return {"files": state["files"]}


async def generate_docs(state: AgentState):
    backend = state["backend"]
    repo_path = state["repo_path"]
    profile = state.get("profile", "readme")
    diagrams = state.get("diagrams", True)
    semaphore = asyncio.Semaphore(max(1, state.get("max_concurrency", 8)))

    async def process(file_path: str):
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception as exc:
            return file_path, f"Error reading file: {exc}"
        prompt = build_doc_prompt(file_path, content, profile, diagrams)
        async with semaphore:
            try:
                doc = await backend.complete(prompt)
                return file_path, sanitize_mermaid_blocks(doc)
            except Exception as exc:
                return file_path, f"Error generating documentation: {exc}"

    results = await asyncio.gather(*(process(fp) for fp in state["files"]))
    return {"documents": dict(results)}


async def generate_index(state: AgentState):
    documents = state["documents"]
    summaries = "\n".join(
        f"- **{path}**: {_extract_summary(doc)}" for path, doc in documents.items()
    )
    profile = state.get("profile", "readme")
    prompt = build_index_prompt("\n".join(state["files"]), summaries, profile)
    index_content = sanitize_mermaid_blocks(await state["backend"].complete(prompt))
    if state.get("diagrams", True):
        index_content += build_diagram_section(state["files"], state["repo_path"])
    return {"index_content": index_content}


workflow = StateGraph(AgentState)
workflow.add_node("analyze_repo", analyze_repo)
workflow.add_node("generate_docs", generate_docs)
workflow.add_node("generate_index", generate_index)
workflow.set_entry_point("analyze_repo")
workflow.add_edge("analyze_repo", "generate_docs")
workflow.add_edge("generate_docs", "generate_index")
workflow.add_edge("generate_index", END)

app = workflow.compile()
