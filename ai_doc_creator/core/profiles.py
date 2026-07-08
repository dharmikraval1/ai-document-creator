# ai_doc_creator/core/profiles.py
"""Output profiles: what the per-file docs and the README should emphasize.

Every profile keeps '### Summary' as the first per-file section — the index
generator extracts it to brief the README synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    file_sections: str      # section instructions for per-file docs
    index_sections: str     # section instructions for the generated README
    file_diagram: bool      # invite a per-file Mermaid flowchart?


PROFILES: dict[str, Profile] = {
    "readme": Profile(
        name="readme",
        file_sections=(
            "### Summary\nA concise 1-2 sentence high-level summary.\n"
            "### Overview\nThe file's role and importance.\n"
            "### Key Classes and Functions\nMain classes/functions, params, returns, behavior.\n"
            "### Usage Examples\nHow to import and use it (if applicable).\n"
        ),
        index_sections=(
            "Include: Project Title, Project Overview, Architecture & Key Components, "
            "Installation, Usage, and Running Tests."
        ),
        file_diagram=True,
    ),
    "api": Profile(
        name="api",
        file_sections=(
            "### Summary\nA concise 1-2 sentence high-level summary.\n"
            "### API Reference\nEvery public class/function: exact signature, parameters "
            "(name, type, default), return type/value, raised errors.\n"
            "### Examples\nA short, correct code example per major API.\n"
            "### Notes\nThread-safety, performance, or stability caveats if visible in the code.\n"
        ),
        index_sections=(
            "Write an API reference index: Project Title, one-paragraph overview, then a "
            "table of modules grouped by area with their key public APIs and links to the "
            "per-file pages. Skip installation walkthroughs."
        ),
        file_diagram=False,
    ),
    "architecture": Profile(
        name="architecture",
        file_sections=(
            "### Summary\nA concise 1-2 sentence high-level summary.\n"
            "### Role in the System\nWhat this component is responsible for and why it exists.\n"
            "### Dependencies & Data Flow\nWhat it imports/calls, what calls it, what data "
            "passes through.\n"
            "### Design Notes\nPatterns, invariants, and trade-offs visible in the code.\n"
        ),
        index_sections=(
            "Write an architecture document: Project Title, System Overview, Component "
            "Responsibilities, Data Flow between components, Key Design Decisions, and "
            "External Dependencies."
        ),
        file_diagram=True,
    ),
    "tutorial": Profile(
        name="tutorial",
        file_sections=(
            "### Summary\nA concise 1-2 sentence high-level summary.\n"
            "### Walkthrough\nExplain the file top-to-bottom as if teaching a newcomer, "
            "in reading order.\n"
            "### Gotchas\nAnything surprising a newcomer would trip over.\n"
        ),
        index_sections=(
            "Write a learning guide: Project Title, What You'll Learn, Prerequisites, "
            "Getting Started, then a suggested reading path through the codebase from "
            "entry points to internals, ending with Next Steps."
        ),
        file_diagram=False,
    ),
}

VALID_PROFILES = ", ".join(sorted(PROFILES))


def get_profile(name: str | None) -> Profile:
    key = (name or "readme").strip().lower()
    if key not in PROFILES:
        raise ValueError(f"Unknown profile '{name}'. Valid profiles: {VALID_PROFILES}.")
    return PROFILES[key]
