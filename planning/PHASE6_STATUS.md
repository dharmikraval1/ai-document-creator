# Phase 6 — Host-Driven Documentation Jobs: Status

**Status:** COMPLETE — MERGED
**Date:** 2026-07-14
**Version:** 2.3.0
**Design:** [2026-07-14-phase6-host-driven-design.md](2026-07-14-phase6-host-driven-design.md)

## What was built

Zero-API-key documentation for MCP clients **without sampling support**
(Claude Code, Cursor, Codex, Antigravity): the client's own model writes the
docs via a four-tool loop while the server does everything else.

- `core/jobs.py`: in-memory `JobStore` (TTL `DOC_JOB_TTL_S`=1800 s, cap
  `MAX_DOC_JOBS`=20, purge-on-access, source cleanup on expiry/finish).
- Tools: `start_doc_job` (same SSRF/LOCAL_ROOT/BYOK-era guards as existing
  tools; GitSource never uses the server GITHUB_TOKEN for remote callers),
  `get_next_files` (1–10 files/batch, ~48 KB budget, profile template
  included, unreadable files self-document as errors), `submit_docs`
  (unknown paths rejected, mermaid sanitized), `finish_doc_job` (refuses
  while files remain; host-written README or TOC fallback; deterministic
  diagram section appended; local write / inline return / PR push with the
  same remote-safety rules as document_repo). Every response carries a
  `NEXT:` instruction so host models drive the loop unaided.
- Also in this release line (v2.2.1): `pick_backend` checks the client's
  declared sampling capability and `SamplingBackend` translates JSON-RPC
  -32601 into an actionable BackendError — no more raw "Method not found".

## Tests

| Phase   | Tests |
|---------|-------|
| Phase 5 | 157   |
| Phase 6 | **168** |

flake8 clean, mypy clean. Coverage: full happy path (local + remote),
finish-too-early, unknown-path rejection, mermaid sanitizing, batching cap,
store expiry + capacity, gating, profile validation.

## Known limitation

Job state is per-process (like the rate limiter): a job must finish on the
instance that started it. Fine for the single-instance deployment.
