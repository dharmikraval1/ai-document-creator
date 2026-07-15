# Usage Guide

Everything you need, step by step. **Pick your situation:**

| I want to... | Jump to |
|---|---|
| Use it in Claude Code | [1a](#1a-claude-code) |
| Use it in Claude Desktop / Cursor / another AI app | [1b](#1b-claude-desktop-cursor-and-other-apps) |
| Use it without installing anything | [2](#2-hosted-server--nothing-to-install) |
| Use it from the terminal | [3](#3-cli) |
| Auto-update docs on every git push | [5](#5-github-action--docs-that-update-themselves) |
| Run my own public server | [6](#6-host-your-own-server) |
| See what I can ask for | [What can I ask?](#what-can-i-ask) |
| Fix a problem | [Troubleshooting](#troubleshooting) |

---

## 1a. Claude Code

**Step 1 — add the server** (one command, needs [uv](https://docs.astral.sh/uv/getting-started/installation/) + git):

```bash
claude mcp add ai-doc-creator -- uvx --from ai-doc-creator ai-doc-creator-mcp
```

**Step 2 — (optional) add your API key.** Skip this if you don't have one — see [No API key?](#no-api-key-no-problem) below.

```bash
claude mcp remove ai-doc-creator
claude mcp add ai-doc-creator --env ANTHROPIC_API_KEY=sk-ant-your-key \
  -- uvx --from ai-doc-creator ai-doc-creator-mcp
```

**Step 3 — just talk to Claude:**

> "Document this project."
>
> "Document https://github.com/user/repo and open a PR with the docs."

Done. Docs land in a `docs/` folder (or as a PR), ending with architecture diagrams.

## 1b. Claude Desktop, Cursor, and other apps

Open the app's MCP settings file:

- **Claude Desktop**: Settings → Developer → Edit Config
- **Cursor**: `~/.cursor/mcp.json`
- **Others** (Windsurf, Codex, Antigravity, ...): the app's MCP/connectors settings — same JSON shape

Paste this:

```json
{
  "mcpServers": {
    "ai-doc-creator": {
      "command": "uvx",
      "args": ["--from", "ai-doc-creator", "ai-doc-creator-mcp"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-your-key" }
    }
  }
}
```

Delete the `env` line if you have no key. Restart the app, then just ask it to document something.

### No API key? No problem.

If your app has no key configured, ask like this instead:

> **"Use start_doc_job to document https://github.com/user/repo. Write the docs yourself batch by batch using get_next_files and submit_docs, then finish the job."**

Your app's **own AI** writes the docs (the one you're already chatting with — no extra cost). The server handles cloning, file batching, diagrams, and delivery. This works in every MCP app.

---

## 2. Hosted server — nothing to install

Use a running instance over the internet. In your app's MCP settings:

```json
{
  "mcpServers": {
    "ai-doc-creator": {
      "type": "http",
      "url": "https://ai-document-creator-agdr.onrender.com/mcp",
      "headers": {
        "X-Provider-API-Key": "sk-ant-your-key",
        "X-Provider": "anthropic"
      }
    }
  }
}
```

- No key? Remove the `headers` block and use the [no-key method](#no-api-key-no-problem) — it works over the hosted server too.
- Your key travels in a header only — it never appears in your chat or the server's logs.
- `X-Provider` can be `anthropic`, `openai`, or `azure`. Add `X-Model` to pick an exact model.
- To receive your docs: say *"return the docs inline"* (they appear in chat) or *"open a PR"* (needs your `github_token`).
- ⏱ Free-tier note: if the server was idle, the first request takes ~1 minute to wake it up.

---

## 3. CLI

```bash
pip install ai-doc-creator
export ANTHROPIC_API_KEY=sk-ant-your-key    # or OPENAI_API_KEY, etc.

ai-doc-creator --repo https://github.com/user/repo --output docs   # a GitHub repo
ai-doc-creator --path . --output docs                              # current folder
ai-doc-creator --path . --provider ollama --model llama3.1         # free, offline
ai-doc-creator --path . --profile architecture                     # pick a style
```

The CLI always needs a provider (there's no AI app to borrow a model from).

---

## 4. Which AI writes the docs?

The server picks automatically, in this order:

1. **A key sent with the request** (header or config) — used only for that request
2. **A key in the server's environment** — for your own local/CLI runs
3. **Your app's model via MCP sampling** — if the app supports it (most don't yet)
4. Otherwise you get a clear message → use the [no-key job flow](#no-api-key-no-problem), which works everywhere

---

## 5. GitHub Action — docs that update themselves

Add `.github/workflows/docs.yml` to any repository:

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
        uses: dharmikraval1/ai-document-creator@v2
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        # with:
        #   path: "src"
        #   profile: "api"

      - name: Open PR with updated docs
        uses: peter-evans/create-pull-request@v6
        with:
          commit-message: "docs: update AI-generated documentation"
          title: "docs: update AI-generated documentation"
          branch: docs/ai-generated
          add-paths: docs
```

One-time setup: repo → **Settings → Secrets and variables → Actions** → add `ANTHROPIC_API_KEY` (or your provider's key).

---

## 6. Host your own server

**One click:** press the button in the [README](README.md#host-your-own-public-server) — the included `render.yaml` blueprint sets up everything (auto-deploy, health checks, safe public defaults).

**Or any Docker host:**

```bash
docker build -t ai-doc-creator .
docker run -p 8000:8000 -e PORT=8000 -e BYOK_ONLY=true \
  -e MCP_ALLOWED_HOSTS=your.public.hostname ai-doc-creator
```

Check it's alive: `https://<your-host>/health`. Users connect at `https://<your-host>/mcp`.

<details>
<summary><strong>All server settings (click to expand)</strong></summary>

| Variable | Default | What it does |
|---|---|---|
| `PORT` | *(unset = stdio)* | Set by the platform; turns on HTTP mode |
| `BYOK_ONLY` | `false` | `true` = never spend the server's own keys on requests |
| `MCP_ALLOWED_HOSTS` | localhost | Your public hostname (Render's is auto-detected) |
| `RATE_LIMIT_RPM` | `20` | Requests/minute per client (`0` = off) |
| `MCP_TRANSPORT` | `both` | `both` / `streamable-http` / `sse` |
| `LOCAL_ROOT` | *(unset)* | Opt-in folder to allow local-file tools remotely |
| `MAX_INLINE_DOC_KB` | `300` | Size cap for docs returned inline |
| `MAX_REPO_MB` | `500` | Max repo clone size |
| `PIPELINE_TIMEOUT_S` | `300` | Max seconds per documentation run |
| `MAX_DIAGRAM_NODES` | `40` | Max boxes per diagram |
| `MAX_DOC_JOBS` / `DOC_JOB_TTL_S` | `20` / `1800` | No-key job limits |

Full list with comments: [`.env.example`](.env.example)
</details>

---

## What can I ask?

Copy any of these into your AI app:

- *"Document this project."*
- *"Document https://github.com/user/repo and open a PR with the docs."*
- *"Document that repo with profile architecture and return the docs inline."*
- *"Generate API reference docs for this folder, no diagrams."*
- *"What files changed since the docs were last generated?"* (drift check — free, no AI calls)
- *"Use start_doc_job to document `<repo>`, write the docs yourself batch by batch, then finish the job."* (the no-key method)

**Options you can mention naturally**: profile (`readme` / `api` / `architecture` / `tutorial`), diagrams on/off, output folder, PR title/branch, private-repo token.

---

## Where do the diagrams show up?

Every generated README ends with two Mermaid diagrams (a project map + a module-dependency chart). They render as **pictures** on GitHub/GitLab and in IDE markdown previews (VS Code, Cursor: open the file → preview). A plain chat terminal shows their text source instead — open the generated file to see the visuals.

---

## Troubleshooting

| You see... | It means... | Do this |
|---|---|---|
| *"This MCP client does not support sampling..."* | No key and your app can't lend its model directly | Use the [no-key method](#no-api-key-no-problem), or add a key |
| *"No LLM available..."* (CLI) | No provider key set | `export ANTHROPIC_API_KEY=...` or `--provider ollama` |
| First hosted request very slow / times out | Free server was asleep | Open `/health` in a browser, wait for it, retry |
| `429 Too Many Requests` | Rate limit hit | Wait a minute (see `Retry-After`) |
| *"...disabled on hosted deployments"* | Local-folder tools don't run on a shared server | Use `document_repo` with a URL, or self-host |
| *"pipeline timed out"* | Repo too big / provider slow | Raise `PIPELINE_TIMEOUT_S`, or document a subfolder |
| Diagrams look like code | Your viewer doesn't render Mermaid | Open the file on GitHub or an IDE preview |

Still stuck? [Open an issue](https://github.com/dharmikraval1/ai-document-creator/issues) — include the exact error text.
