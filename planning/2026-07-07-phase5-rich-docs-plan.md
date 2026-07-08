# Phase 5 — Rich Documentation: Implementation Plan

**Design:** [2026-07-07-phase5-rich-docs-design.md](2026-07-07-phase5-rich-docs-design.md)

1. **`core/diagrams.py`** — `build_dependency_mermaid` (Python + JS/TS import
   scan, internal edges only, relative-import resolution, caps, escaping),
   `build_structure_mermaid` (dir tree), `sanitize_mermaid_blocks` (validate
   fenced mermaid; downgrade invalid blocks to plain fences). Unit tests.
2. **`core/profiles.py`** — `Profile` dataclass + `readme` / `api` /
   `architecture` / `tutorial`; `get_profile` with clear error. All profiles
   keep `### Summary` first (the index summarizer depends on it). Unit tests.
3. **`core/graph.py`** — profile/diagram-aware `build_doc_prompt` /
   `build_index_prompt` (backward-compatible defaults); `generate_docs`
   sanitizes outputs; `generate_index` appends deterministic diagram section
   in code, then sanitizes.
4. **Wiring** — `_run_pipeline` + re-index path (server) and CLI pass
   `profile`/`diagrams`; new tool params with validation; CLI `--profile`,
   `--no-diagrams`. Version 2.2.0.
5. **Tests** — diagrams (deps py/js, structure, caps, hostile labels, <2
   edges → None), sanitizer (valid kept / invalid downgraded), profiles,
   prompt content per profile, end-to-end `_run_pipeline` with FakeBackend
   (diagram section present in README; per-file invalid mermaid downgraded),
   tool param validation.
6. **Docs & ship** — README + USAGE updates, PHASE5_STATUS, PR → main.
