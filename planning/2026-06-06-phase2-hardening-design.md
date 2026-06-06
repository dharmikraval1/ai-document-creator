# Phase 2 — Hardening Design Spec

**Date:** 2026-06-06  
**Branch:** `feature/phase2-hardening` (branches from `feature/multi-provider-foundation`)  
**Status:** Approved — ready for implementation  
**Reviewer:** dharmikraval1  

---

## 1. Goal

Harden the AI Document Creator MCP server and CLI for production deployment. Phase 1 delivered a working multi-provider pipeline with 43 tests. Phase 2 adds the defensive infrastructure required before exposing the server publicly:

- SSRF and path-traversal protection
- Repo and file size caps
- Global concurrency cap and per-call timeouts
- Retry / backoff on transient LLM errors
- DNS-rebinding protection with an allowlist
- `/health` endpoint
- Structured JSON logging with per-request IDs
- PR-based push: `document_repo` can open a GitHub PR with the generated docs
- BYOK-first mode for multi-tenant SSE deployments

**Non-goals for Phase 2:** incremental/cache layer (Phase 3), output profiles (Phase 4), packaging (Phase 5).

---

## 2. Architecture

### 2.1 New modules

| Module | Responsibility |
|--------|---------------|
| `core/guards.py` | SSRF URL validation, repo size cap, local path traversal check |
| `core/retry.py` | Tenacity-based retry decorator for `CompletionBackend.complete()` |
| `core/logging_config.py` | JSON structured logger; `request_id` via `contextvars` |

### 2.2 Modified files

| File | Change summary |
|------|---------------|
| `core/sources.py` | `GitSource.__init__` calls `validate_repo_url` before creating temp dir |
| `core/backends.py` | `ProviderBackend.complete()` wrapped with `with_retry()` |
| `core/config.py` | Add `pipeline_timeout_s: int = 300` field |
| `mcp_server_impl.py` | Global semaphore · per-call timeout · JSON logging · `/health` · BYOK flag · DNS allowlist · PR params |
| `requirements.txt` | Add `tenacity`, `PyGithub` |

### 2.3 Data flow (updated)

```
tool call
  │
  ├─ inject request_id (contextvars)
  ├─ acquire global semaphore (MAX_CONCURRENT_PIPELINES)
  │
  ├─ validate_repo_url / validate_local_path  [guards.py]
  │
  └─ asyncio.wait_for(_run_pipeline, timeout=config.pipeline_timeout_s)
       │
       ├─ source.prepare()           [sources.py — GitSource calls guards]
       ├─ validate_repo_size()       [guards.py — post-clone size check]
       ├─ FileTraverser.traverse()
       ├─ pick_backend()             [BYOK flag applied here]
       ├─ workflow_app.ainvoke()     [graph.py — backend.complete() uses retry]
       ├─ DocumentationWriter.write_docs()
       └─ (optional) push_docs_pr() [PR creation via PyGithub]
```

---

## 3. SSRF Guard (`core/guards.py`)

### 3.1 `validate_repo_url(url: str) -> None`

Raises `ValueError` with a descriptive message if any of the following are true:

**Scheme check:**
- Scheme is not `https`. HTTP is blocked on the remote server; only HTTPS is acceptable for cloning untrusted URLs.

**Host resolution check:**
- Parses the hostname from the URL.
- Resolves the hostname to its IP address(es) via `socket.getaddrinfo`.
- Rejects any IP that falls within:
  - `127.0.0.0/8` — loopback
  - `10.0.0.0/8` — private class A
  - `172.16.0.0/12` — private class B
  - `192.168.0.0/16` — private class C
  - `169.254.0.0/16` — link-local / AWS metadata endpoint (`169.254.169.254`)
  - `100.64.0.0/10` — carrier-grade NAT (RFC 6598)
  - `::1/128` — IPv6 loopback
  - `fc00::/7` — IPv6 unique local
- Rejects hostnames: `metadata.google.internal`, `metadata.internal`

**Implementation note:** DNS resolution happens at validation time (before `GitPython` clones). This is sufficient for the current threat model; a full TOCTOU-safe guard (re-checking the resolved IP at connect time) is deferred to Phase 5 when we control the network layer.

### 3.2 `validate_repo_size(repo_path: str, max_mb: int = 500) -> None`

Called immediately after `Repo.clone_from` succeeds. Walks the cloned directory tree, sums file sizes, and raises `ValueError` if the total exceeds `max_mb`. Default 500 MB; configurable via `MAX_REPO_MB` env var.

Rationale: GitHub's advertised repo size is unreliable for forks and LFS repos. A post-clone check is the only reliable gate.

### 3.3 `validate_local_path(path: str) -> None`

Only enforced when `LOCAL_ROOT` env var is set. Raises `ValueError` if the resolved absolute path does not start with `LOCAL_ROOT`. Prevents an MCP tool caller from passing `path="/etc"` to `document_local_project`.

When `LOCAL_ROOT` is not set (default for local/stdio deployments), all readable directories are allowed — consistent with the trust model of a local agent.

---

## 4. Resilience

### 4.1 Retry (`core/retry.py`)

```
with_retry(backend: CompletionBackend, max_attempts: int = 3) -> CompletionBackend
```

Returns a `RetryBackend` wrapper that delegates `complete()` to the wrapped backend and retries on transient failures using `tenacity`:

- **Wait:** `wait_exponential(multiplier=1, min=1, max=8)` → ~1 s, 2 s, 4 s
- **Stop:** `stop_after_attempt(max_attempts)`
- **Retry predicate:** retries on any `Exception` except `BackendError` (configuration errors) and `ValueError` (bad input). In practice this catches network errors, `httpx.RemoteProtocolError`, and rate-limit `429` responses from providers.
- **Before sleep:** logs a WARNING with attempt number and exception message (uses the `request_id` from context).

`ProviderBackend.__init__` wraps its own `complete` via `with_retry`. `FakeBackend` and `SamplingBackend` are not wrapped (tests use `FakeBackend` directly; sampling errors should propagate immediately).

### 4.2 Per-call timeout

`_run_pipeline` is invoked inside `asyncio.wait_for`:

```python
await asyncio.wait_for(_run_pipeline(...), timeout=config.pipeline_timeout_s)
```

`config.pipeline_timeout_s` defaults to `300` (5 minutes). It is overridable via the `PIPELINE_TIMEOUT_S` env var and also as an explicit parameter to `resolve_config`. On `asyncio.TimeoutError`, the outer `except` block in each tool function returns a structured error string:

```
Error: pipeline timed out after {n}s. The repository may be too large or the LLM provider is unresponsive.
```

### 4.3 Global concurrency cap

A module-level semaphore in `mcp_server_impl.py`:

```python
_pipeline_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_PIPELINES", "3")))
```

Each tool function acquires this semaphore (using `async with`) before calling `_run_pipeline`. The 4th concurrent call blocks rather than launching a new unbounded set of LLM requests. Default of 3 is conservative for a single-instance Render deployment with provider rate limits.

---

## 5. PR-Based Push

### 5.1 New parameters on `document_repo`

```python
push_as_pr: bool = False
pr_branch: str | None = None   # default: "docs/ai-generated-{YYYYMMDD-HHMMSS}"
pr_title:  str | None = None   # default: "docs: AI-generated documentation"
```

These parameters are ignored for `document_local_project` — local projects don't have a remote origin to push to.

### 5.2 `push_docs_pr` function

Private async function in `mcp_server_impl.py`:

```
push_docs_pr(
    repo_url: str,
    docs_dir: str,
    branch: str,
    title: str,
    github_token: str,
) -> str   # returns the PR HTML URL
```

**Steps (all via PyGithub Contents API — no second clone):**

1. Parse `owner/repo` from `repo_url` (supports `https://github.com/owner/repo[.git]`).
2. Use `PyGithub` (`github.Github(github_token)`) to get the repo object.
3. Read the default branch name and its HEAD SHA.
4. Create branch `branch` off the default branch HEAD via `repo.create_git_ref(f"refs/heads/{branch}", sha)`.
5. For each `.md` file in `docs_dir`:
   - Read the file content from disk.
   - Target path in repo: `docs/{filename}`.
   - Try `repo.get_contents(target_path, ref=branch)` — if found, call `repo.update_file`; otherwise call `repo.create_file`.
   - Commit message: `"docs: add AI-generated documentation"`.
6. Create the pull request:
   ```python
   pr = gh_repo.create_pull(
       title=title,
       body="Auto-generated documentation by AI Document Creator.",
       head=branch,
       base=default_branch,
   )
   ```
7. Return `pr.html_url`.

**Failure handling:**
- If `github_token` is `None` (neither passed nor in `GITHUB_TOKEN` env), `push_as_pr` is silently skipped and the report includes: `⚠️ push_as_pr=True was requested but no GitHub token is available — skipping PR creation.`
- All `PyGithub` exceptions are caught and surfaced in the report as a non-fatal warning (docs are still written locally).
- Only works with `github.com` URLs. Non-GitHub remotes log a warning and skip.

---

## 6. Infrastructure

### 6.1 DNS-rebinding protection

Change:
```python
TransportSecuritySettings(enable_dns_rebinding_protection=False)
```
To:
```python
TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_parse_allowed_hosts(),
)
```

`_parse_allowed_hosts()` reads `MCP_ALLOWED_HOSTS` env var (comma-separated, default `"localhost,127.0.0.1"`). This restores the security that was explicitly disabled in Phase 1 while allowing local development without configuration.

### 6.2 `/health` endpoint

```python
@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    return JSONResponse({"status": "ok", "version": "2.0.0"})
```

Returns HTTP 200 with JSON body. Used by Render health checks and any upstream monitoring. `version` is a module-level constant `__version__ = "2.0.0"` at the top of `mcp_server_impl.py`.

### 6.3 Structured logging (`core/logging_config.py`)

Two components:

**`RequestIdFilter`:** A `logging.Filter` subclass that injects the current `request_id` (from a `contextvars.ContextVar[str]`) into every log record as `record.request_id`. Falls back to `"-"` when no request is active (e.g., startup logs).

**`JsonFormatter`:** A `logging.Formatter` subclass that serialises each record as a single-line JSON object:
```json
{"timestamp": "2026-06-06T12:00:00.000Z", "level": "INFO", "logger": "mcp_server_impl", "request_id": "a1b2c3", "message": "Cloning https://github.com/..."}
```

**`setup_logging(json_mode: bool = False) -> None`:** Configures the root logger. When `LOG_FORMAT=json` env var is set, installs `JsonFormatter + RequestIdFilter`. Otherwise installs the existing plain-text format (unchanged). Called once at module startup in `mcp_server_impl.py`.

**`request_id` lifecycle:** Each tool function generates a `uuid4` short ID at entry and sets it via `REQUEST_ID_VAR.set(short_id)`. All log lines emitted during that tool call carry the same ID — allowing full tracing of a single documentation request across modules.

### 6.4 BYOK-first mode

When `BYOK_ONLY=true` env var is set, `pick_backend` in `mcp_server_impl.py` is called with a `DocConfig` that has `provider=None` regardless of what the tool caller passed. This forces the sampling fallback (host LLM) and prevents the operator's `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from being silently consumed on behalf of callers.

Intended for multi-tenant SSE deployments where each user is expected to use the host's own model via MCP sampling, not the operator's paid API key.

When `BYOK_ONLY` is not set (the default), behaviour is unchanged from Phase 1: an explicit `provider` param wins, then env-detected provider, then sampling.

---

## 7. Configuration Reference

All new configuration is via environment variables with safe defaults:

| Env var | Default | Description |
|---------|---------|-------------|
| `MAX_CONCURRENT_PIPELINES` | `3` | Max simultaneous `_run_pipeline` executions |
| `PIPELINE_TIMEOUT_S` | `300` | Seconds before a pipeline call times out |
| `MAX_REPO_MB` | `500` | Max cloned repo size in megabytes |
| `LOCAL_ROOT` | _(unset)_ | If set, restricts `document_local_project` to paths under this dir |
| `MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts for DNS-rebinding allowlist |
| `LOG_FORMAT` | _(unset)_ | Set to `json` to enable structured JSON logging |
| `BYOK_ONLY` | _(unset)_ | Set to `true` to force host-model sampling regardless of env keys |

---

## 8. Testing Strategy

Target: **≥ 62 passing tests** (up from 43).

| File | New tests | What they cover |
|------|-----------|-----------------|
| `tests/test_guards.py` | ~10 | SSRF blocklist (private IP, loopback, link-local, metadata), valid URL passes, size cap triggers/passes, local path traversal blocked/allowed |
| `tests/test_retry.py` | ~5 | Retry fires on transient error, stops at max_attempts, does not retry `BackendError`, exponential delay called |
| `tests/test_mcp_tools.py` | +4 | Global semaphore blocks 4th caller, timeout raises friendly string, BYOK flag forces sampling, `/health` returns 200 |
| `tests/test_pr_push.py` | ~6 | PR push called with mocked PyGithub, branch auto-named correctly, skipped gracefully when no token, non-GitHub URL skipped with warning |

All existing 43 tests must remain green. No test may use `unittest.mock.patch` on network I/O that isn't already abstracted — use the existing `FakeBackend` and monkeypatch patterns established in Phase 1.

---

## 9. Definition of Done

- [ ] `pytest -q` reports ≥ 62 passing, 0 failing
- [ ] `mypy core/ mcp_server_impl.py --strict` passes (or suppressions are justified inline)
- [ ] `flake8` passes with no errors
- [ ] `document_repo(..., push_as_pr=True)` opens a real PR on a test repo (manual smoke test)
- [ ] `/health` returns `{"status":"ok","version":"2.0.0"}` in SSE mode
- [ ] `LOG_FORMAT=json` produces valid JSON on every log line
- [ ] No hardcoded secrets, tokens, or IPs anywhere in the codebase
- [ ] All new env vars documented in `.env.example`
- [ ] `feature/phase2-hardening` merged to `main` via PR
