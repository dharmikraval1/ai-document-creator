# AI Document Creator

An AI-powered documentation generator exposed as an **MCP server** and a **CLI**. It documents both **GitHub repositories** and **local projects**, using **any LLM** — Anthropic, OpenAI, Azure OpenAI, AWS Bedrock, or Ollama — or the **MCP host's own model via sampling** (zero API cost to the operator).

> **Status:** Phase 1 (Foundation) complete. See [planning/PHASE1_STATUS.md](planning/PHASE1_STATUS.md) for the roadmap and how to resume work.

## How it works

Documentation generation is two independent choices over one async pipeline:

- **Source** — where the files come from: `GitSource` (clone a URL) or `LocalSource` (read a path on disk).
- **Backend** — which LLM writes the docs: `ProviderBackend` (any provider via a key) or `SamplingBackend` (the MCP host's model). `pick_backend` chooses: a configured provider wins; otherwise host sampling; otherwise a clear error.

The pipeline (`core/graph.py`) traverses files, generates per-file docs concurrently (bounded by a semaphore), then synthesizes a top-level `README.md`.

## Directory structure

```
.
├── main.py                  # CLI entry point
├── mcp_server_impl.py       # MCP server (stdio + SSE); tools: document_local_project, document_repo
├── core/
│   ├── config.py            # DocConfig + provider/model resolution
│   ├── backends.py          # CompletionBackend: ProviderBackend, SamplingBackend, FakeBackend, pick_backend
│   ├── sources.py           # Source: LocalSource, GitSource, token masking
│   ├── graph.py             # async, backend-agnostic LangGraph pipeline
│   ├── file_traverser.py    # walks a tree, skips ignored/binary/oversized files
│   └── doc_writer.py        # writes the generated markdown tree + index
├── tests/                   # pytest suite (config, backends, sources, graph, mcp tools)
├── planning/                # design spec, implementation plan, status/handoff
├── Dockerfile               # container for the MCP server (Render/SSE)
├── requirements.txt
└── .env.example
```

## Installation

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux
```

Then copy `.env.example` to `.env` and set the keys for one provider (or use `--provider ollama` for a local model).

## Usage — CLI

```bash
# Document a GitHub repo
python main.py --repo https://github.com/user/repo --output docs

# Document a local project
python main.py --path . --output docs

# Pick a provider/model explicitly
python main.py --path . --provider anthropic
python main.py --path . --provider ollama --model llama3.1
```

The CLI requires a provider key (there is no MCP host to sample from). If none is configured it exits with an actionable message.

## Usage — MCP server

Configure the server in an MCP host (Claude Code, Cursor, Antigravity, …). It exposes two tools:

- `document_local_project(path, output_dir, provider?, model?)` — document a folder on the local machine.
- `document_repo(repo_url, output_dir, github_token?, provider?, model?)` — clone and document a GitHub repo.

When no provider key is set, the tools fall back to the host's own model via MCP sampling.

Run modes:
- **stdio** (default): `python mcp_server_impl.py`
- **SSE** (set `PORT`): used for the hosted deployment (e.g. Render).

## LLM providers

| Provider | Configure via |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` (or `--provider anthropic`) |
| OpenAI | `OPENAI_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` + endpoint/deployment (see `.env.example`) |
| AWS Bedrock | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| Ollama (local) | `--provider ollama` (no key) |

## Running tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

## Roadmap

Phase 1 (this) is the foundation. Hardening, incremental/drift docs, output profiles + Mermaid diagrams, and packaging + a GitHub Action follow — each detailed in [planning/](planning/).
