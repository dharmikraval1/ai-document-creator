# AI Document Creator

[![CI](https://github.com/dharmikraval1/ai-document-creator/actions/workflows/ci.yml/badge.svg)](https://github.com/dharmikraval1/ai-document-creator/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-doc-creator)](https://pypi.org/project/ai-doc-creator/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Ask your AI assistant to document any codebase — and get a full set of docs with architecture diagrams, delivered as files or a pull request.**

You say:

> *"Document the repo https://github.com/user/repo and open a PR with the docs."*

You get:

- 📄 A markdown doc for **every file** — what it does, key functions, how to use it
- 📖 A polished **README** for the whole project
- 📊 **Architecture diagrams** (Mermaid) — a project map and a module-dependency chart, generated from real imports so they're always accurate
- 🔀 Delivered where you want: local folder, inline in chat, or a **GitHub pull request**

Works inside **Claude Code, Claude Desktop, Cursor, Codex, Antigravity** — any app that supports MCP — plus a plain CLI and a GitHub Action.

## Get started in 1 minute

### In Claude Code

```bash
claude mcp add ai-doc-creator -- uvx --from ai-doc-creator ai-doc-creator-mcp
```

Then just ask: *"Document this project."* That's it.

### In Claude Desktop, Cursor, or any other MCP app

Add this to the app's MCP settings (Cursor: `~/.cursor/mcp.json`):

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

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and `git` installed — nothing else.

### Don't want to install anything?

Point your MCP app at the hosted server instead — see the [Usage Guide](USAGE.md#2-hosted-server--nothing-to-install).

## Do I need an API key?

**No.** Pick whichever fits you:

| You have... | What to do |
|---|---|
| **Nothing — just an AI app** | Ask: *"Use start_doc_job to document `<repo>`, write the docs yourself batch by batch, then finish the job."* Your app's own AI writes the docs — free. |
| **An API key** (Anthropic/OpenAI/Azure/Bedrock) | Add it to the config — fastest, everything generated in one call |
| **Ollama on your machine** | `provider="ollama"` — free and fully offline |

## Pick a documentation style

Add `profile` to your request (or `--profile` in the CLI):

- `readme` *(default)* — classic project README
- `api` — API reference with signatures and parameters
- `architecture` — components, data flow, and diagrams
- `tutorial` — a guided walkthrough for newcomers

> 💡 Diagrams render as pictures on GitHub and in IDE markdown previews. A plain terminal shows their Mermaid source — that's normal.

## The CLI (no AI app needed)

```bash
pip install ai-doc-creator
export ANTHROPIC_API_KEY=sk-ant-...          # any supported provider
ai-doc-creator --repo https://github.com/user/repo --output docs
ai-doc-creator --path . --profile architecture
```

## Docs that update themselves (GitHub Action)

```yaml
- uses: dharmikraval1/ai-document-creator@v2
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Every push regenerates your docs and opens a PR. [Full workflow →](USAGE.md#5-github-action--docs-that-update-themselves)

## Host your own public server

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/dharmikraval1/ai-document-creator)

One click. Safe defaults are pre-configured: your API keys are never spent on other people's requests (they bring their own key in a header, or their app's AI writes the docs), rate limiting is on, and auto-deploy tracks `main`.

## Good to know

- **Incremental**: re-runs only process files that changed (content-hash cache) — fast and cheap.
- **Your key stays private**: keys travel in config/headers only — never in chat messages, logs, or output.
- **Hardened**: SSRF guards, request sandboxing, size/time/rate limits. Details in [SECURITY.md](SECURITY.md).

## Learn more

- 📖 [Usage Guide](USAGE.md) — step-by-step setup for every app, all options, troubleshooting
- 🤝 [Contributing](CONTRIBUTING.md) · 🔒 [Security policy](SECURITY.md) · 🗂 [Design docs](planning/)

## License

[MIT](LICENSE) — free for any use.
