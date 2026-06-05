# core/graph.py
from __future__ import annotations

import asyncio
import os
import re
from typing import Dict, List, TypedDict

from langgraph.graph import END, StateGraph

from .backends import CompletionBackend


class AgentState(TypedDict):
    repo_path: str
    files: List[str]
    documents: Dict[str, str]
    index_content: str
    backend: CompletionBackend
    max_concurrency: int


def build_doc_prompt(file_path: str, code_content: str) -> str:
    # f-strings avoid str.format brace issues when code contains { }.
    return (
        "You are an expert technical writer. Generate comprehensive documentation "
        "for the following code file.\n\n"
        f"File Path: {file_path}\n\n"
        "Code Content:\n"
        f"{code_content}\n\n"
        "Output Format: Markdown\n\n"
        "Include these sections:\n"
        "### Summary\nA concise 1-2 sentence high-level summary.\n"
        "### Overview\nThe file's role and importance.\n"
        "### Key Classes and Functions\nMain classes/functions, params, returns, behavior.\n"
        "### Usage Examples\nHow to import and use it (if applicable).\n"
    )


def build_index_prompt(file_list: str, doc_summaries: str) -> str:
    return (
        "You are an expert technical writer. Generate a premium, comprehensive README.md "
        "for the following repository.\n\n"
        f"Repository Structure (Files):\n{file_list}\n\n"
        f"Generated Documentation Summaries:\n{doc_summaries}\n\n"
        "Output Format: Markdown\n\n"
        "Include: Project Title, Project Overview, Architecture & Key Components, "
        "Installation, Usage, and Running Tests."
    )


def _extract_summary(doc_content: str) -> str:
    match = re.search(r"### Summary\s*([\s\S]*?)(?=(?:##|###)|$)", doc_content, re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    cleaned = re.sub(r"#+\s+.*", "", doc_content).strip()
    cleaned = "\n".join(line for line in cleaned.splitlines() if line.strip())
    return cleaned[:200] + "..." if len(cleaned) > 200 else cleaned


async def analyze_repo(state: AgentState):
    return {"files": state["files"]}


async def generate_docs(state: AgentState):
    backend = state["backend"]
    repo_path = state["repo_path"]
    semaphore = asyncio.Semaphore(state.get("max_concurrency", 8))

    async def process(file_path: str):
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception as exc:
            return file_path, f"Error reading file: {exc}"
        prompt = build_doc_prompt(file_path, content)
        async with semaphore:
            try:
                return file_path, await backend.complete(prompt)
            except Exception as exc:
                return file_path, f"Error generating documentation: {exc}"

    results = await asyncio.gather(*(process(fp) for fp in state["files"]))
    return {"documents": dict(results)}


async def generate_index(state: AgentState):
    documents = state["documents"]
    summaries = "\n".join(
        f"- **{path}**: {_extract_summary(doc)}" for path, doc in documents.items()
    )
    prompt = build_index_prompt("\n".join(state["files"]), summaries)
    index_content = await state["backend"].complete(prompt)
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
