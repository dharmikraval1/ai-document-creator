# Phase 6 — Host-Driven Documentation Jobs: Design Spec

**Date:** 2026-07-14
**Branch:** claude/mcp-ai-document-tool-19j3v3
**Goal:** Zero-API-key documentation in **every** MCP client — Claude Code,
Cursor, Codex, Antigravity — including the vast majority that do not
implement MCP sampling.

## Problem

`document_repo` needs a model. Today's keyless path (MCP sampling) requires
the *client* to serve `sampling/createMessage`, which most hosts don't
(empirically verified: Claude Code answers `-32601 Method not found`).
So keyless users of those tools hit a dead end, however clear the error.

## Insight

Tool calls are the one channel every MCP client supports. So invert the
flow: the server stops calling a model and instead feeds source files to the
**host's own model as tool results**; the model writes the docs in its own
session (zero marginal cost to the user — it's the model they're already
talking to) and submits them back via tools. The server still owns
everything models are bad at: cloning, traversal, guards, batching,
deterministic Mermaid diagrams, writing output, PR push.

## Tools (the "doc job" flow)

1. `start_doc_job(repo_url? | path?, profile, diagrams) -> job briefing`
   Validates (same SSRF/LOCAL_ROOT rules as existing tools), prepares the
   source, traverses files, creates an in-memory job. Returns `job_id`,
   file count, and explicit next-step instructions the host model follows.
2. `get_next_files(job_id, max_files=3) -> file contents + writing template`
   Returns the next batch of file paths + contents plus the profile's
   section template. Repeatable until empty.
3. `submit_docs(job_id, docs) -> progress`
   Accepts `{file_path: markdown}` for previously handed-out files
   (unknown paths rejected), sanitizes any Mermaid, stores them, and says
   what to do next.
4. `finish_doc_job(job_id, index_markdown?, push_as_pr?, github_token?,
   pr_branch?, pr_title?, return_docs?) -> report`
   Refuses while files remain. Appends the deterministic diagram section to
   the index (host-written, or a generated table-of-contents fallback),
   then reuses the existing output paths: local write, inline return
   (`MAX_INLINE_DOC_KB` cap), or PR push — with the same remote-mode
   safety rules (temp dir, no server GITHUB_TOKEN for remote callers).

Every response ends with a `NEXT:` line so any competent host model can
drive the loop without bespoke prompting.

## Job store (`core/jobs.py`)

In-memory, per-process: `{job_id: DocJob}` holding source handle, repo
path, pending/sent/done file sets, docs, profile/diagrams/remote flags.
Abuse bounds: `MAX_DOC_JOBS` (default 20) concurrent jobs, TTL
`DOC_JOB_TTL_S` (default 1800 s) with purge on every access; expired or
finished jobs clean up their cloned temp dirs. Remote callers are already
rate-limited per client.

Honest limitation (same class as the rate limiter): per-instance state —
a job must finish on the instance that started it. Fine for the current
single-instance deployment; documented.

## Batching

`get_next_files` caps a batch at `max_files` (1–10) and ~48 KB of content,
always including at least one file — keeps tool results inside host
context budgets; huge files ride alone.

## Non-goals

- Replacing the one-shot tools — `document_repo` stays the best path when
  a key or sampling exists (parallel generation, one call).
- Cross-instance job persistence (needs a shared store; not warranted yet).
