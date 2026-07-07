# Phase 4 — Distribution & Public Access: Status

**Branch:** claude/mcp-ai-document-tool-19j3v3
**Status:** COMPLETE — MERGE-READY
**Date:** 2026-07-07
**Design:** [2026-07-07-phase4-distribution-design.md](2026-07-07-phase4-distribution-design.md)
**Plan:** [2026-07-07-phase4-distribution-plan.md](2026-07-07-phase4-distribution-plan.md)

## What was built

### 1. Installable package (`ai_doc_creator/`)
- `core/` → `ai_doc_creator/core/`, `main.py` → `ai_doc_creator/cli.py`,
  `mcp_server_impl.py` → `ai_doc_creator/server.py`; root `main.py` /
  `mcp_server_impl.py` remain as thin shims, so the existing deployment's
  `CMD ["python", "mcp_server_impl.py"]` keeps working.
- `pyproject.toml`: PyPI name **ai-doc-creator**, dynamic version from
  `ai_doc_creator.__version__` (**2.1.0**), dev extra, console scripts
  `ai-doc-creator` (CLI) and `ai-doc-creator-mcp` (server).
- Fixes the Phase 3 mypy duplicate-module error; `mypy ai_doc_creator` is clean.

### 2. Streamable HTTP transport (SSE preserved)
- HTTP mode (PORT set) serves `/mcp` (Streamable HTTP, current MCP spec),
  `/sse` + `/messages/` (legacy), `/health` — from one process.
- `MCP_TRANSPORT` env: `both` (default) | `streamable-http` | `sse`.
- Verified live: initialize handshake on `/mcp` (protocol 2025-06-18),
  SSE endpoint event on `/sse`, health probe 200.

### 3. Per-request BYOK via headers
- `X-Provider-API-Key`, `X-Provider` (defaults to `anthropic` when a key is
  sent), `X-Model`. Tool args win over headers for provider/model.
- `DocConfig.api_key` is `repr=False`; the key is passed explicitly to the
  provider client (`init_chat_model` / AzureChatOpenAI); env is never mutated,
  so concurrent requests cannot cross-contaminate.
- `BYOK_ONLY=true`: server env keys are never spent; header-key requests use
  their own key; keyless requests fall back to host sampling.
- Bedrock is excluded from header BYOK (needs an AWS credential pair).

### 4. Remote-mode safety
- `document_local_project` / `check_doc_drift` are refused on HTTP deployments
  unless `LOCAL_ROOT` is set (explicit operator opt-in).
- `document_repo` remotely ignores `output_dir` → per-request temp dir,
  cleaned up afterwards; incremental off (no manifest in a temp dir).
- New `return_docs=True` param inlines generated markdown in the response,
  capped by `MAX_INLINE_DOC_KB` (default 300).

### 5. Rate limiting (`core/ratelimit.py`)
- In-memory sliding window per client (first `X-Forwarded-For` hop, else peer
  address), `RATE_LIMIT_RPM` (default 20, 0 disables), `/health` exempt,
  429 + `Retry-After`. Known limitation: per-instance state.

### 6. Collateral
- MIT `LICENSE`, GitHub Actions CI (flake8 + mypy + pytest on 3.11/3.12),
  `.flake8` config, MCP-registry `server.json`, README rewritten around the
  three consumption paths, `.env.example` updated, Dockerfile installs the
  package and runs `python -m ai_doc_creator.server`.

## Test count

| Phase   | Tests |
|---------|-------|
| Phase 1 | 43    |
| Phase 2 | 84    |
| Phase 3 | 100   |
| Phase 4 | **127** |

flake8: clean. mypy: clean (was 1 error). All verified with the suite plus a
live HTTP smoke test (health / initialize / SSE / rate-limit 429s).

## Owner follow-ups (manual, need your accounts)

1. **Redeploy the hosted instance** (Render — the Dockerfile deployment).
   After merging, set env: `BYOK_ONLY=true`, `MCP_ALLOWED_HOSTS=<your-host>`,
   `LOG_FORMAT=json`. New endpoint for users: `https://<your-host>/mcp`
   (old `/sse` URL still works).
2. **Publish to PyPI**: `pip install build twine && python -m build &&
   twine upload dist/*` (needs your PyPI token). Package name: `ai-doc-creator`.
3. **Submit to the MCP registry**: fill the deployment URL into `server.json`
   (`remotes[0].url`), then follow
   https://registry.modelcontextprotocol.io docs (`mcp-publisher publish`).
4. **Tag a release**: `git tag v2.1.0 && git push origin v2.1.0`, create a
   GitHub Release — helps discovery.

## Possible Phase 5 ideas (not started)
- GitHub Action wrapper (`uses: dharmikraval1/ai-document-creator@v2`) for
  docs-in-CI on every push.
- Output profiles (API reference / tutorial / architecture) + Mermaid diagrams.
- Shared-store rate limiting + OAuth if the hosted tier grows beyond one instance.
