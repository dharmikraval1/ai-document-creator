# Phase 4 — Distribution & Public Access: Implementation Plan

**Date:** 2026-07-07
**Design:** [2026-07-07-phase4-distribution-design.md](2026-07-07-phase4-distribution-design.md)

Each task ends in a runnable state (tests + flake8 green) and one commit.

## Task 1 — Package restructure + pyproject
- `git mv core ai_doc_creator/core`; add `ai_doc_creator/__init__.py` with `__version__`.
- `git mv main.py ai_doc_creator/cli.py`, `git mv mcp_server_impl.py ai_doc_creator/server.py`;
  switch their imports to package-relative; wrap server `__main__` block into `main()`.
- Root shims `main.py` / `mcp_server_impl.py` re-exporting + runnable (deployment CMD compat).
- `pyproject.toml`: setuptools, dynamic version, runtime deps, dev extra, console scripts.
- Update test imports (`core.` → `ai_doc_creator.core.`, `mcp_server_impl` → `ai_doc_creator.server`).
- Fix env-leaky test `test_gitsource_no_token_leaves_url_untouched` (delenv GITHUB_TOKEN).
- Verify: `pip install -e .`, both console scripts import, full suite green, mypy duplicate-module error gone.

## Task 2 — DocConfig.api_key + ProviderBackend explicit key
- `DocConfig.api_key` (`repr=False`), threaded through `resolve_config`.
- `ProviderBackend` passes `api_key` to `init_chat_model` / AzureChatOpenAI when set.
- Tests: repr masking; init_chat_model receives the key; azure override.

## Task 3 — Header BYOK + BYOK_ONLY sharpening in server
- `_request_headers(ctx)` helper (safe on stdio → `{}`).
- Tools merge `X-Provider-API-Key` / `X-Provider` / `X-Model` into config
  (explicit tool args still win for provider/model).
- `BYOK_ONLY`: env-key configs stripped; header-key configs honored; no env mutation.
- Tests: header extraction, BYOK_ONLY with/without header key, stdio no-op.

## Task 4 — Remote-mode gating + temp output + return_docs
- `_is_remote()`; gate local-FS tools unless `LOCAL_ROOT` set.
- `document_repo`: remote → temp output dir + incremental off; `return_docs`
  param inlines docs capped by `MAX_INLINE_DOC_KB` (default 300).
- Tests: gating on/off, temp-dir isolation, cap behavior.

## Task 5 — Rate-limit middleware
- `core/ratelimit.py`: `SlidingWindowLimiter` + pure-ASGI middleware, XFF-aware,
  `/health` exempt, `RATE_LIMIT_RPM` (default 20, 0=off).
- Tests: window math, 429 + Retry-After, exemption, XFF parsing.

## Task 6 — HTTP app: streamable-http + SSE composition
- `build_http_app()` in server.py combining `streamable_http_app()` routes with
  SSE routes, session-manager lifespan, rate-limit middleware; `MCP_TRANSPORT`
  selector; `main()` runs uvicorn on it when PORT set, stdio otherwise.
- Verify **live**: run with PORT, curl `/health`, initialize handshake on `/mcp`,
  `/sse` responds with event stream.
- Tests: route presence per MCP_TRANSPORT value.

## Task 7 — Collateral
- LICENSE (MIT), `.github/workflows/ci.yml` (flake8 + pytest, py3.11/3.12),
  `server.json`, README rewrite, `.env.example` additions
  (`MCP_TRANSPORT`, `RATE_LIMIT_RPM`, `MAX_INLINE_DOC_KB`), Dockerfile
  (`pip install .`, `python -m ai_doc_creator.server`).

## Task 8 — Status + push
- `planning/PHASE4_STATUS.md` (what shipped, test count, PyPI publish steps,
  redeploy notes for the existing Render deployment, registry submit steps).
- Push branch `claude/mcp-ai-document-tool-19j3v3`.
