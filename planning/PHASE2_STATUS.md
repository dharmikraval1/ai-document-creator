# Phase 2 Status — Hardening

**Last updated:** 2026-06-06  
**Branch:** `feature/phase2-hardening`  
**Test status:** ✅ 84 passing

## What was built

- `core/guards.py` — SSRF URL validation (RFC 1918 + metadata blocklist + IPv4-mapped IPv6 +
  `fe80::/10`; stdlib predicates), repo size cap, local path sandbox (`LOCAL_ROOT`).
- `core/retry.py` — `with_retry()` tenacity wrapper; exponential backoff (1 s → 2 s → 4 s capped
  at 8 s); does not retry `BackendError` / `ValueError` / `TypeError`.
- `core/logging_config.py` — `setup_logging(json_mode)`, `_JsonFormatter`, `REQUEST_ID_VAR`
  context var injected into every log record via `_RequestIdFilter`.
- `core/config.py` — `DocConfig.pipeline_timeout_s` (default 300 s, env `PIPELINE_TIMEOUT_S`).
- `core/sources.py` — `GitSource.prepare()` now calls `validate_repo_url` + `validate_repo_size`
  before any network I/O.
- `core/backends.py` — `pick_backend()` wraps `ProviderBackend` with `with_retry()`.
- `mcp_server_impl.py` — full rewrite:
  - Module-level `asyncio.Semaphore(MAX_CONCURRENT_PIPELINES)` caps parallel pipelines.
  - `asyncio.wait_for(pipeline, timeout=config.pipeline_timeout_s)` per tool call.
  - `BYOK_ONLY=true` forces sampling backend regardless of operator env keys.
  - DNS-rebinding protection re-enabled; `MCP_ALLOWED_HOSTS` env for allowlist.
  - `@mcp.custom_route("/health")` returns `{"status":"ok","version":"2.0.0"}`.
  - `setup_logging(json_mode)` called once at startup.
  - `REQUEST_ID_VAR` set at the top of each tool call.
  - `document_repo` gains `push_as_pr`, `pr_branch`, `pr_title` parameters.
  - `_push_docs_pr` commits `.md` files to a branch via PyGithub Contents API and opens a PR.

## Security improvements (Phase 2 additions)

- SSRF blocklist uses stdlib `ip.is_private / is_loopback / is_link_local / is_multicast /
  is_reserved / is_unspecified` — covers IPv4-mapped IPv6 (`::ffff:10.0.0.1`), `fe80::/10`,
  all RFC1918 + carrier-NAT ranges without a manual network list.
- `LOCAL_ROOT` sandbox prevents directory traversal when server mounts arbitrary paths.
- `MAX_REPO_MB` prevents OOM from cloning giant repositories.

## How to resume (fresh device)

```bash
git clone https://github.com/dharmikraval1/ai-document-creator.git
cd ai-document-creator
git checkout feature/phase2-hardening
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest -q  # expect 84 passed
```

## Remaining phases

- **Phase 3 — Incremental + drift:** `core/cache.py` content-hash manifest; only regenerate
  changed files; `check_doc_drift` MCP tool.
- **Phase 4 — Profiles + diagrams:** `core/profiles.py` (readme / api-reference / onboarding);
  `core/diagrams.py` (Mermaid architecture + dependency graphs).
- **Phase 5 — Packaging + GitHub Action:** `pyproject.toml` / `uvx` entry-point; MCP registry
  listing; `action.yml` that opens a PR with generated docs on every push.
