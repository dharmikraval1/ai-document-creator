# Project Status & Handoff — AI Document Creator

> Read this first when resuming on any device. It captures where the work stands and how to continue.

**Last updated:** 2026-06-05
**Active branch:** `feature/multi-provider-foundation` (pushed to `origin` = github.com/dharmikraval1/ai-document-creator.git)
**Test status:** ✅ 43 passing (`pytest`)

## What this project is

An AI documentation generator exposed as an **MCP server** (and a CLI). It documents both **GitHub repos** and **local projects**, using **any LLM** (Anthropic / OpenAI / Azure / Bedrock / Ollama via a provider key) **or the MCP host's own model via sampling** (zero operator cost). Full vision in [planning/2026-06-05-scalable-mcp-doc-generator-design.md](2026-06-05-scalable-mcp-doc-generator-design.md).

The design is organised as two axes over one pipeline:
- **Source** — `GitSource` (clone a URL) or `LocalSource` (read a path).
- **Backend** — `ProviderBackend` (any provider) or `SamplingBackend` (host LLM), chosen by `pick_backend`.

## Phase 1 (Foundation) — ✅ COMPLETE

Delivered on this branch:
- `core/config.py` — `DocConfig` + `resolve_config` (provider detection, model resolution).
- `core/backends.py` — `CompletionBackend` interface, `FakeBackend`, `ProviderBackend` (multi-provider via `init_chat_model`, Azure special-cased), `SamplingBackend` (MCP host sampling), `pick_backend`. List-block content is flattened to text.
- `core/sources.py` — `Source`, `LocalSource`, `GitSource` (replaces the old `RepoLoader`), `mask_token` so tokens never hit logs.
- `core/graph.py` — async, backend-agnostic LangGraph pipeline with `asyncio.Semaphore` bounded concurrency (no import-time LLM).
- `main.py` — CLI rewritten: `--repo`/`--path`, `--output`, `--provider`, `--model`.
- `mcp_server_impl.py` — two MCP tools: `document_local_project` and `document_repo`; stdio + SSE transports.
- Removed `core/repo_loader.py`, `scratch_test_push.py`, `verification_script.py` (superseded).
- Full `tests/` pytest suite (config, backends, sources, graph, mcp tools).

Each unit went through implementer + spec-compliance review + code-quality review (with fixes applied), e.g.: list-content flattening bug (Anthropic), `resolve_config` kwarg crash, nullable MCP tool params, bounded-concurrency test, token privatisation.

**Final full-branch review (2026-06-05): ✅ MERGE-READY** — no blocking issues; state contract consistent across CLI/MCP/graph, `pick_backend` flow coherent, async correct, `requirements.txt` complete, 43 tests pass, no dangling references. The README was brought in sync with the new architecture as the one follow-up. Ready to merge `feature/multi-provider-foundation` → `main`.

## How to resume (fresh device)

```bash
git clone https://github.com/dharmikraval1/ai-document-creator.git
cd ai-document-creator
git checkout feature/multi-provider-foundation

# recreate the virtualenv (.venv is gitignored)
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt # macOS/Linux

.venv/Scripts/python.exe -m pytest -q   # expect 43 passing
```

Configure an LLM by copying `.env.example` to `.env` and setting one provider's keys, or pass `--provider ollama` for a local model. The CLI requires a provider key (no host to sample from); the MCP tools fall back to host sampling when no key is set.

## Remaining work (next sessions)

Each phase has its own spec→plan→implement cycle. The full plan for Phase 1 is in [planning/2026-06-05-foundation-multi-provider-sources.md](2026-06-05-foundation-multi-provider-sources.md). Next:

- **Final review of Phase 1** — a holistic full-branch code review, then merge `feature/multi-provider-foundation` → `main` (open a PR or fast-forward). *This is the immediate next step.*
- **Phase 2 — Hardening:** SSRF/abuse guards + repo size/file caps on the remote server; global concurrency cap; per-call timeouts + retry/backoff; re-enable DNS-rebinding protection with an allowlist; `/health` + structured logging; PR-based push (the old `push_to_repo` was removed and returns here, safer); BYOK-first remote so the operator key isn't the silent default.
- **Phase 3 — Incremental + drift:** `core/cache.py` (`.docai/manifest.json` content hashes) so only changed files regenerate; a `check_doc_drift` tool.
- **Phase 4 — Profiles + diagrams:** `core/profiles.py` (readme / api-reference / onboarding) and `core/diagrams.py` (Mermaid architecture + dependency graphs).
- **Phase 5 — Packaging + GitHub Action:** `pyproject.toml` for `uvx documentation-ai`, MCP registry listing, and an `action.yml` that opens a PR with generated docs on every push.

## Notes / gotchas

- This repo is the **real project**. There is a wrapper folder one level up (`DocumentationAI/`) that accidentally shares the same git remote — ignore it; everything needed lives here.
- Deferred-to-Hardening items intentionally NOT in Phase 1: `_run_pipeline` returns errors as strings (no `isError` framing); `output_dir` resolves against the server CWD; no retries/timeouts/SSRF.
