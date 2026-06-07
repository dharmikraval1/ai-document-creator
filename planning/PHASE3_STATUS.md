# Phase 3 — Incremental + Drift Status

**Branch:** feature/phase3-incremental  
**Status:** MERGE-READY  
**Date:** 2026-06-07

## What Was Built

### Task 1 — Content-Hash Manifest Cache (`core/cache.py`)
- `MANIFEST_FILENAME`, `hash_file`, `compute_hashes`, `load_manifest`, `save_manifest`, `filter_changed`
- SHA-256 content hashing with 64 KiB chunked reads
- Manifest stored at `{output_dir}/.ai-docs-manifest.json`
- Commit: 7fdf96a

### Task 2 — Incremental Pipeline Wiring (`mcp_server_impl.py`)
- `_run_pipeline` now loads manifest, calls `filter_changed`, passes only changed files to LLM
- Unchanged files' existing docs merged with new docs before index regeneration
- `incremental: bool = True` param on both `document_local_project` and `document_repo`
- `_load_existing_doc` helper reads existing `.md` files from output dir
- Manifest saved after every successful run
- Commit: 920a40d

### Task 3 — Drift Detection Tool (`check_doc_drift`)
- Pure I/O MCP tool (no LLM, no semaphore, no timeout)
- Reports new files, modified files, and deleted files vs. last manifest
- Commit: ff7c496

## Test Count

| Phase     | Tests |
|-----------|-------|
| Phase 1   | 43    |
| Phase 2   | 84    |
| Phase 3   | **100** |

## Flake8
Clean

## Mypy
1 error (non-blocking): `core/cache.py` found twice under different module names ("cache" and "core.cache") — resolution requires `--explicit-package-bases` or adjusting `MYPYPATH`. No logic errors reported.
