# Phase 4 — Distribution & Public Access: Design Spec

**Date:** 2026-07-07
**Branch:** claude/mcp-ai-document-tool-19j3v3
**Goal:** Anyone in the world can use this tool — either by installing it locally
(with their own API key, or keyless via MCP host sampling) or by pointing their
MCP host at the hosted endpoint (bring-your-own-key via headers). Ship it
production-grade: no key leakage, no server-filesystem exposure, abuse-limited,
CI-verified, and discoverable.

## Problems this phase solves

| # | Problem | Consequence today |
|---|---------|-------------------|
| 1 | No packaging (`pyproject.toml`) | Nobody can `pip install` / `uvx` the tool; adoption requires git clone + venv |
| 2 | Top-level module names `core`, `main` | Unpublishable to PyPI (name collisions); mypy duplicate-module error |
| 3 | Hosted transport is SSE only | SSE is deprecated in the MCP spec; new hosts expect Streamable HTTP |
| 4 | No per-request BYOK channel | Remote users cannot supply their own key; passing keys as tool args would leak them into chat transcripts |
| 5 | `document_local_project` / `check_doc_drift` exposed remotely | Remote callers can read the *server's* filesystem when `LOCAL_ROOT` is unset |
| 6 | `output_dir` is an arbitrary server path | Remote callers can write to arbitrary server paths |
| 7 | Remote callers never receive per-file docs | Only the index is inlined in the report; the rest lands on the server's disk |
| 8 | No rate limiting | A public endpoint can be trivially flooded |
| 9 | No LICENSE, CI, or registry metadata | Not adoptable, not trustworthy, not discoverable |

## Design

### 1. Package layout (installable, PyPI-ready)

```
ai_doc_creator/            # the installable package
├── __init__.py            # __version__ = "2.1.0" (single source of truth)
├── cli.py                 # was main.py
├── server.py              # was mcp_server_impl.py
└── core/                  # moved verbatim from core/ (already uses relative imports)
main.py                    # thin shim → ai_doc_creator.cli  (back-compat)
mcp_server_impl.py         # thin shim → ai_doc_creator.server (back-compat: existing
                           #   deployment CMD "python mcp_server_impl.py" keeps working)
pyproject.toml             # setuptools; dynamic version from ai_doc_creator.__version__
```

Console scripts:
- `ai-doc-creator` → `ai_doc_creator.cli:main`
- `ai-doc-creator-mcp` → `ai_doc_creator.server:main`

So after `pip install ai-doc-creator` (or zero-install `uvx ai-doc-creator-mcp`),
an MCP host config is one line. Runtime deps live in `[project.dependencies]`;
dev tools (pytest/flake8/black/isort/mypy) move to `[project.optional-dependencies].dev`.
`requirements.txt` stays as a pin-free convenience file for the Dockerfile.

### 2. Transport — Streamable HTTP with SSE kept alive

HTTP mode (PORT set) serves **both** transports from one uvicorn process:

- `/mcp` — Streamable HTTP (current MCP spec)
- `/sse` + `/messages/` — legacy SSE, so the already-deployed endpoint's existing
  clients keep working after redeploy
- `/health` — unchanged

Implementation: compose one Starlette app from `mcp.streamable_http_app()` routes
plus the SSE-specific routes of `mcp.sse_app()` (deduping the shared custom
routes), with a lifespan that runs the streamable-HTTP session manager.
`MCP_TRANSPORT` env (`both` | `streamable-http` | `sse`, default `both`) selects,
so an operator can turn either off. stdio remains the default without PORT.
Verified live (curl initialize handshake) before merge.

### 3. Per-request BYOK via HTTP headers

Remote users supply credentials in **headers**, never in tool arguments
(tool args are model-visible and transcript-logged; headers are not):

- `X-Provider-API-Key: <key>` — the user's provider key
- `X-Provider: anthropic|openai|azure` — optional, defaults to `anthropic` when a key is sent
- `X-Model: <model>` — optional model override

Plumbing:
- `DocConfig.api_key: str | None` with `repr=False` (never appears in logs/repr).
- `ProviderBackend` passes `api_key` explicitly to `init_chat_model` (and Azure),
  instead of only reading env — explicit key wins over env. Bedrock is excluded
  from header BYOK (needs an AWS credential pair, not one key).
- Tools read headers from `ctx.request_context.request` when present (HTTP
  transports only; stdio has no request).
- `BYOK_ONLY=true` semantics sharpened: the server's env keys are **never** used
  for requests; a request with its own header key uses that key; a request
  without one falls back to host sampling (or a clear error). Per-request keys
  are handed to the backend object only — the environment is never mutated, so
  concurrent requests can never cross-contaminate keys.

### 4. Remote-mode safety

`_is_remote()` = PORT set. When remote:
- `document_local_project` and `check_doc_drift` are refused unless the operator
  explicitly set `LOCAL_ROOT` (conscious opt-in to expose a directory).
- `document_repo` ignores the caller's `output_dir` and writes to a fresh temp
  dir (cleaned after the run) — remote callers cannot write arbitrary server paths.
- New tool param `return_docs: bool = False` inlines the generated per-file docs
  in the response (capped at `MAX_INLINE_DOC_KB`, default 300 KB total) so remote
  users actually receive their docs; `push_as_pr=True` remains the way to get
  them committed to the repo.
- Incremental caching is auto-disabled remotely (temp dir has no prior manifest).

### 5. Rate limiting

`ai_doc_creator/core/ratelimit.py`: an in-memory sliding-window limiter keyed by
client IP (first `X-Forwarded-For` hop when present — Render/Fly terminate TLS at
a proxy), applied as pure-ASGI middleware in HTTP mode. `RATE_LIMIT_RPM`
(default 20, `0` disables). Exempts `/health`. Returns `429` JSON with
`Retry-After`. Explicitly documented limitation: per-instance state — multi-
instance deployments need a shared store (future work; single instance is the
current deployment reality).

### 6. Release collateral

- **LICENSE** — MIT (required for adoption).
- **CI** — GitHub Actions: flake8 + pytest on 3.11/3.12 for every push/PR.
- **server.json** — MCP registry metadata (registry.modelcontextprotocol.io),
  listing both the PyPI package and the hosted remote endpoint.
- **README** — rewritten around three consumption paths: `uvx` local install,
  hosted endpoint + headers, CLI; copy-paste config for Claude Code, Claude
  Desktop, Cursor; full env-var reference; security model section.
- **Dockerfile** — installs the package (`pip install .`), runs
  `python -m ai_doc_creator.server`; old CMD path still works via shim.

## Explicit non-goals (recorded so nobody chases them blind)

- **OAuth / account system** on the hosted endpoint — header BYOK + rate limit +
  BYOK_ONLY already make the public endpoint cost-safe; OAuth adds friction with
  no revenue model behind it yet.
- **Distributed rate limiting / autoscaling** — the scaling story to "millions of
  users" is `uvx` local installs (zero marginal server cost), not one giant
  hosted instance. The hosted endpoint is a demo/convenience tier.
- **Publishing to PyPI from CI** — repo is made publish-ready (`pyproject.toml`,
  version single-sourced); the actual `twine upload` needs the owner's PyPI
  token and is a one-command manual step documented in the status doc.

## Security review checklist applied to the new surface

- Keys: header-only intake; `repr=False`; never logged (JSON logger already
  masks nothing by name — we never put the key in a log record); never written
  into env; explicit-arg passing to the LangChain client.
- SSRF: unchanged guards on repo URLs; DNS-rebinding protection still enabled;
  `MCP_ALLOWED_HOSTS` must include the public hostname (documented — this
  already bit the Render deploy in Phase 2).
- Filesystem: remote mode cannot read (local tools gated) or write (temp-dir
  output) outside per-request temp space.
- DoS: request rate limit (new) + pipeline semaphore + pipeline timeout +
  repo-size cap + per-file-size cap (existing).
