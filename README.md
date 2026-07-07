# AI Document Creator

[![CI](https://github.com/dharmikraval1/ai-document-creator/actions/workflows/ci.yml/badge.svg)](https://github.com/dharmikraval1/ai-document-creator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

AI-powered documentation generator, exposed as an **MCP server** and a **CLI**. Point it at a **GitHub repository** or a **local project** and it writes per-file docs plus a synthesized `README.md` — using **any LLM** (Anthropic, OpenAI, Azure OpenAI, AWS Bedrock, Ollama) with your key, or **your MCP host's own model via sampling with no key at all**.

## Use it in 60 seconds

### Option A — run it locally in your MCP host (recommended)

With [uv](https://docs.astral.sh/uv/) installed, no clone, no venv:

```bash
# Claude Code
claude mcp add ai-doc-creator -- uvx --from ai-doc-creator ai-doc-creator-mcp
```

Claude Desktop / Cursor / any MCP host (`mcpServers` JSON):

```json
{
  "mcpServers": {
    "ai-doc-creator": {
      "command": "uvx",
      "args": ["--from", "ai-doc-creator", "ai-doc-creator-mcp"],
      "env": { "ANTHROPIC_API_KEY": "sk-..." }
    }
  }
}
```

The `env` block is optional — leave it out and the server uses your MCP host's model via sampling (zero API cost).

> Until the package is on PyPI you can substitute
> `uvx --from git+https://github.com/dharmikraval1/ai-document-creator ai-doc-creator-mcp`.

### Option B — use a hosted endpoint (nothing to install)

Point your MCP host at a deployment's Streamable HTTP endpoint and bring your own key in headers:

```json
{
  "mcpServers": {
    "ai-doc-creator": {
      "type": "http",
      "url": "https://<your-deployment-host>/mcp",
      "headers": {
        "X-Provider-API-Key": "sk-...",
        "X-Provider": "anthropic"
      }
    }
  }
}
```

Keys travel in **headers**, never in tool arguments, so they stay out of chat transcripts and logs. Legacy clients can still connect via `https://<host>/sse`.

### Option C — CLI

```bash
pip install ai-doc-creator     # or: pip install git+https://github.com/dharmikraval1/ai-document-creator
ai-doc-creator --repo https://github.com/user/repo --output docs
ai-doc-creator --path . --provider ollama --model llama3.1
```

The CLI needs a provider key (there is no MCP host to sample from).

## MCP tools

| Tool | What it does |
|---|---|
| `document_repo(repo_url, ...)` | Clone a GitHub repo and document it. `push_as_pr=True` opens a PR with the docs; `return_docs=True` inlines the generated markdown in the response (capped by `MAX_INLINE_DOC_KB`). |
| `document_local_project(path, ...)` | Document a folder on the machine the server runs on. Disabled on hosted deployments unless the operator sets `LOCAL_ROOT`. |
| `check_doc_drift(path, output_dir)` | Report new/modified/deleted files since the last documentation run (no LLM calls). |

All documentation runs are **incremental** by default: a content-hash manifest skips unchanged files, so re-runs only pay for what changed.

## How it works

Two independent choices over one async pipeline:

- **Source** — `GitSource` (clone a URL) or `LocalSource` (read a path).
- **Backend** — `ProviderBackend` (any provider, via env key or per-request header key) or `SamplingBackend` (the MCP host's model). `pick_backend` chooses: an explicit key wins; otherwise a configured provider; otherwise host sampling; otherwise a clear error.

The pipeline traverses files, generates per-file docs concurrently (bounded by a semaphore), then synthesizes a top-level `README.md`.

## LLM providers

| Provider | Configure via |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` env, or `X-Provider-API-Key` header |
| OpenAI | `OPENAI_API_KEY` env, or header |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` + endpoint/deployment (see `.env.example`), or header |
| AWS Bedrock | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (env only) |
| Ollama (local) | `provider="ollama"` (no key) |
| None | MCP host sampling — the host's model writes the docs |

## Hosting your own public endpoint

The included `Dockerfile` runs anywhere that supplies a `PORT` (Render, Fly.io, Railway, ...). The server then serves Streamable HTTP at `/mcp`, legacy SSE at `/sse`, and a health probe at `/health`.

Recommended env for a public deployment:

| Variable | Value | Why |
|---|---|---|
| `MCP_ALLOWED_HOSTS` | your public hostname (e.g. `your-app.onrender.com`) | DNS-rebinding protection rejects unknown Host headers |
| `BYOK_ONLY` | `true` | never spend *your* keys on strangers — users bring keys in headers or use sampling |
| `RATE_LIMIT_RPM` | `20` (default) | per-client request cap; `0` disables |
| `LOG_FORMAT` | `json` | structured logs |
| `MCP_TRANSPORT` | `both` (default) / `streamable-http` / `sse` | which HTTP transports to serve |

## Security model

- **Keys**: header-only intake for remote users; passed explicitly to the provider client; never written to env, logs, or `repr()`; `BYOK_ONLY=true` guarantees the server's own keys are never used for requests.
- **SSRF**: repo URLs must be HTTPS and must not resolve to private/reserved address space; DNS-rebinding protection on the HTTP transports.
- **Filesystem**: hosted deployments refuse local-filesystem tools (unless `LOCAL_ROOT` opts in) and write repo docs to per-request temp dirs — callers can't read or write server paths.
- **Abuse limits**: per-client rate limit, bounded pipeline concurrency, pipeline timeout, repo-size cap, per-file-size cap.

## Development

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q          # 127 tests
flake8 && mypy ai_doc_creator --ignore-missing-imports
```

Design specs, implementation plans, and phase status live in [planning/](planning/).

## License

[MIT](LICENSE)
