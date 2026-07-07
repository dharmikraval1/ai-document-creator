# How to Use AI Document Creator

A step-by-step guide for every way to use the tool. Pick the path that fits you:

| You are... | Go to |
|---|---|
| Using Claude Code, Claude Desktop, Cursor, or another MCP app | [1. Use it inside your AI app](#1-use-it-inside-your-ai-app-mcp) |
| Wanting zero setup — just a URL | [2. Use a hosted endpoint](#2-use-a-hosted-endpoint) |
| A terminal person | [3. Use the CLI](#3-use-the-cli) |
| Hosting it for your team or the world | [4. Deploy your own server](#4-deploy-your-own-server) |
| Wanting docs to update themselves in CI | [5. GitHub Action](#5-github-action--docs-that-update-themselves) |

---

## 1. Use it inside your AI app (MCP)

### Claude Code

```bash
claude mcp add ai-doc-creator -- uvx --from ai-doc-creator ai-doc-creator-mcp
```

> No PyPI yet / want the newest code? Use the git source instead:
> `claude mcp add ai-doc-creator -- uvx --from git+https://github.com/dharmikraval1/ai-document-creator ai-doc-creator-mcp`

Then just ask, in plain language:

> "Document the repo https://github.com/user/repo and open a PR with the docs."
>
> "Generate documentation for this project folder."
>
> "What files changed since the docs were last generated?"

### Claude Desktop

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "ai-doc-creator": {
      "command": "uvx",
      "args": ["--from", "ai-doc-creator", "ai-doc-creator-mcp"]
    }
  }
}
```

### Cursor / Windsurf / other MCP hosts

Same JSON shape as Claude Desktop, in the app's MCP settings file
(Cursor: `~/.cursor/mcp.json`).

### Which model writes the docs?

- **No configuration** → the server asks *your host's model* to write the docs
  (MCP sampling). Zero API cost, nothing to set up.
- **Your own key** → add an `env` block for faster, dedicated generation:

```json
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
```

Works the same with `OPENAI_API_KEY`, Azure (see `.env.example`), AWS Bedrock
credentials, or a local Ollama (`provider="ollama"` — fully free and offline).

### Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (provides `uvx`), and `git` on your PATH.
- Alternative without uv: `pip install ai-doc-creator`, then use
  `"command": "ai-doc-creator-mcp"` in the config.

---

## 2. Use a hosted endpoint

If someone runs a public instance (see section 4), you need nothing installed:

```json
{
  "mcpServers": {
    "ai-doc-creator": {
      "type": "http",
      "url": "https://<deployment-host>/mcp",
      "headers": {
        "X-Provider-API-Key": "sk-ant-...",
        "X-Provider": "anthropic"
      }
    }
  }
}
```

- `X-Provider` can be `anthropic`, `openai`, or `azure`; add `X-Model` to pick
  a specific model. Keys travel only in headers — they never appear in the
  chat transcript.
- On a hosted endpoint use `document_repo` with `return_docs=True` (docs come
  back inline) or `push_as_pr=True` with your `github_token` (docs arrive as a
  PR on your repo).
- Older hosts that only speak SSE can use `https://<deployment-host>/sse`.

---

## 3. Use the CLI

```bash
pip install ai-doc-creator            # or pipx install ai-doc-creator
export ANTHROPIC_API_KEY=sk-ant-...   # any supported provider works

# Document a GitHub repo into ./docs
ai-doc-creator --repo https://github.com/user/repo --output docs

# Document the current directory
ai-doc-creator --path . --output docs

# Free & local with Ollama
ai-doc-creator --path . --provider ollama --model llama3.1
```

The CLI requires a provider (there is no MCP host to sample from).

---

## 4. Deploy your own server

### One-click on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/dharmikraval1/ai-document-creator)

The included [`render.yaml`](render.yaml) blueprint configures everything:
Docker build, **auto-deploy on every push to main**, health checks, and safe
public defaults (`BYOK_ONLY=true`, rate limiting on). The server automatically
allows Render's hostname, so no host configuration is needed.

After deploy, verify: `https://<your-app>.onrender.com/health` →
`{"status": "ok", "version": "..."}`. Your MCP URL is `https://<your-app>.onrender.com/mcp`.

### Any other Docker host

```bash
docker build -t ai-doc-creator .
docker run -p 8000:8000 -e PORT=8000 -e BYOK_ONLY=true \
  -e MCP_ALLOWED_HOSTS=your.public.hostname ai-doc-creator
```

### Key environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | *(unset = stdio)* | Set by the platform; enables HTTP mode |
| `BYOK_ONLY` | `false` | `true` = never spend the server's keys on requests |
| `MCP_ALLOWED_HOSTS` | localhost | Public hostname(s); auto-includes Render's |
| `RATE_LIMIT_RPM` | `20` | Per-client requests/minute (`0` disables) |
| `MCP_TRANSPORT` | `both` | `both` / `streamable-http` / `sse` |
| `LOCAL_ROOT` | *(unset)* | Opt-in sandbox to enable local-FS tools remotely |
| `MAX_INLINE_DOC_KB` | `300` | Cap for `return_docs=True` responses |

Full list in [`.env.example`](.env.example).

---

## 5. GitHub Action — docs that update themselves

Add `.github/workflows/docs.yml` to **any repository** and its documentation
regenerates on every push, arriving as a reviewable PR:

```yaml
name: Update docs
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  docs:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - name: Generate documentation
        uses: dharmikraval1/ai-document-creator@main   # pin to a tag (e.g. @v2) once released
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        # optional inputs:
        # with:
        #   path: "src"
        #   output: "docs"
        #   provider: "openai"
        #   model: "gpt-4o-mini"

      - name: Open PR with updated docs
        uses: peter-evans/create-pull-request@v6
        with:
          commit-message: "docs: update AI-generated documentation"
          title: "docs: update AI-generated documentation"
          branch: docs/ai-generated
          add-paths: docs
```

Setup: add your provider key once in the repo's
**Settings → Secrets and variables → Actions** (e.g. `ANTHROPIC_API_KEY`).
Any provider works — set the matching env var and `provider` input.

---

## Tool reference

### `document_repo`

| Param | Default | Notes |
|---|---|---|
| `repo_url` | *(required)* | HTTPS GitHub URL |
| `github_token` | – | For private repos / opening PRs. Remote callers must supply their own. |
| `provider`, `model` | auto | Override the LLM |
| `incremental` | `true` | Skip unchanged files (content-hash cache) |
| `push_as_pr` | `false` | Commit docs to a branch + open a PR |
| `pr_branch`, `pr_title` | auto | PR customization |
| `return_docs` | `false` | Inline the generated markdown in the response |
| `output_dir` | `docs` | Local runs only; hosted runs use a temp dir |

### `document_local_project`

| Param | Default | Notes |
|---|---|---|
| `path` | `.` | Project folder |
| `output_dir` | `docs` | Where markdown is written |
| `provider`, `model`, `incremental` | | Same as above |

### `check_doc_drift`

Reports new / modified / deleted files vs. the last documentation run.
No LLM calls — instant and free.

---

## Troubleshooting

- **"No LLM available"** — set a provider key, use `provider="ollama"`, or run
  inside an MCP host that supports sampling.
- **421 / rejected requests on a hosted server** — the public hostname is
  missing from `MCP_ALLOWED_HOSTS` (Render deployments handle this
  automatically).
- **429 Too Many Requests** — you hit the rate limit; wait for the
  `Retry-After` seconds or raise `RATE_LIMIT_RPM` on your own deployment.
- **"this tool reads the server's local filesystem..."** — you called a
  local-FS tool on a hosted endpoint; use `document_repo`, or self-host with
  `LOCAL_ROOT` set.
- **Pipeline timed out** — raise `PIPELINE_TIMEOUT_S`, or document a smaller
  repo (`MAX_REPO_MB` caps clone size).
