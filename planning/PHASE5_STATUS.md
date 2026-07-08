# Phase 5 — Rich Documentation: Status

**Branch:** claude/mcp-ai-document-tool-19j3v3
**Status:** COMPLETE — MERGED
**Date:** 2026-07-07
**Version:** 2.2.0
**Design:** [2026-07-07-phase5-rich-docs-design.md](2026-07-07-phase5-rich-docs-design.md)
**Plan:** [2026-07-07-phase5-rich-docs-plan.md](2026-07-07-phase5-rich-docs-plan.md)

## What was built

### 1. Deterministic Mermaid diagrams (`core/diagrams.py`)
- `build_dependency_mermaid`: Python (incl. relative imports) + JS/TS import
  scanning, internal edges only, degree-ranked node cap
  (`MAX_DIAGRAM_NODES`, default 40), quoted/escaped labels, `None` when
  there's nothing meaningful to draw.
- `build_structure_mermaid`: directory-tree chart with the same cap.
- Appended to every generated README under `## Architecture Diagrams` by
  code (never by the model) — always-valid syntax.
- Verified against this repo itself: both diagrams correct and readable.

### 2. Validated model-drawn flow charts
- `readme`/`architecture` per-file prompts invite a small Mermaid flowchart
  for files with non-trivial control flow.
- `sanitize_mermaid_blocks` runs on every per-file doc and the index:
  unknown diagram type or unbalanced brackets → block downgraded to a plain
  ```text fence (content preserved, page never breaks).

### 3. Output profiles (`core/profiles.py`)
- `readme` (default), `api`, `architecture`, `tutorial` — distinct per-file
  sections and README structure; all keep `### Summary` first (the index
  summarizer depends on it).
- Exposed as `profile` on both MCP tools (validated, clear error listing
  valid names) and `--profile` on the CLI; `diagrams` / `--no-diagrams`
  alongside. Wired through `_run_pipeline`, the incremental re-index path,
  and the CLI.

## Test count

| Phase   | Tests |
|---------|-------|
| Phase 4 | 132   |
| Phase 5 | **157** |

flake8 clean, mypy clean. Integration tests prove: diagrams section present
in generated README, absent with `diagrams=False`, invalid model-drawn
mermaid downgraded, profile text reaches both prompts, unknown profile
rejected on both tools.
