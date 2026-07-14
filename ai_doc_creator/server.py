# ai_doc_creator/server.py
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import uuid

from dotenv import load_dotenv

load_dotenv()

from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from github import Github, GithubException  # noqa: E402

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from . import __version__  # noqa: E402
from .core.config import DocConfig, resolve_config  # noqa: E402
from .core.backends import pick_backend  # noqa: E402
from .core.guards import validate_local_path, validate_repo_url  # noqa: E402
from .core.logging_config import REQUEST_ID_VAR, setup_logging  # noqa: E402
from .core.sources import GitSource, LocalSource, Source  # noqa: E402
from .core.file_traverser import FileTraverser  # noqa: E402
from .core.graph import app as workflow_app, generate_index as _generate_index  # noqa: E402
from .core.doc_writer import DocumentationWriter  # noqa: E402
from .core.cache import compute_hashes, filter_changed, load_manifest, save_manifest  # noqa: E402
from .core.diagrams import sanitize_mermaid_blocks  # noqa: E402
from .core.graph import build_diagram_section  # noqa: E402
from .core.jobs import DocJob, JobError, JobStore, new_job_id  # noqa: E402
from .core.profiles import get_profile  # noqa: E402
from .core.ratelimit import RateLimitMiddleware  # noqa: E402

setup_logging(json_mode=os.getenv("LOG_FORMAT", "").lower() == "json")
logger = logging.getLogger(__name__)

_BYOK_ONLY: bool = os.getenv("BYOK_ONLY", "").lower() == "true"
_pipeline_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_PIPELINES", "3")))
_job_store = JobStore()

# Per-batch content budget for get_next_files (keeps tool results inside
# host context limits; at least one file is always included).
_JOB_BATCH_BYTES = 48 * 1024


def _parse_allowed_hosts() -> list[str]:
    raw = os.getenv(
        "MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,localhost:*,127.0.0.1:*"
    )
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    # Render injects its public hostname; allow it automatically so a
    # blueprint deploy works without hand-configuring MCP_ALLOWED_HOSTS.
    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host and render_host not in hosts:
        hosts.append(render_host)
    return hosts


def _is_remote() -> bool:
    """True when serving over HTTP (PORT set) — i.e. callers are not the machine owner."""
    return bool(os.getenv("PORT"))


_LOCAL_TOOL_DISABLED_MSG = (
    "Error: this tool reads the server's local filesystem and is disabled on "
    "hosted deployments. Use `document_repo` with a repository URL instead, or "
    "ask the operator to expose a directory explicitly via LOCAL_ROOT."
)

# Providers that accept a single per-request API key over headers.
# (bedrock needs an AWS credential pair; ollama is a local, keyless runtime.)
_BYOK_PROVIDERS = frozenset({"anthropic", "openai", "azure"})


def _request_headers(ctx: Context | None) -> dict[str, str]:
    """Lower-cased HTTP headers of the current request; {} on stdio."""
    if ctx is None:
        return {}
    try:
        request = ctx.request_context.request
    except (AttributeError, ValueError):
        return {}
    if request is None or not hasattr(request, "headers"):
        return {}
    return {k.lower(): v for k, v in request.headers.items()}


def _resolve_request_config(
    provider: str | None,
    model: str | None,
    incremental: bool,
    ctx: Context | None,
    profile: str = "readme",
    diagrams: bool = True,
) -> DocConfig | str:
    """Build the request's DocConfig, folding in BYOK headers.

    Keys travel in headers — never in tool arguments, which are model-visible
    and transcript-logged. Explicit tool args win over headers for provider and
    model. Returns an error string (not an exception) for invalid combinations
    so tools can surface it directly.
    """
    headers = _request_headers(ctx)
    api_key = headers.get("x-provider-api-key") or None
    provider = provider or headers.get("x-provider") or None
    model = model or headers.get("x-model") or None
    if api_key:
        provider = provider or "anthropic"
        if provider not in _BYOK_PROVIDERS:
            return (
                f"Error: provider '{provider}' does not support per-request API "
                f"keys; supported: {', '.join(sorted(_BYOK_PROVIDERS))}."
            )
    try:
        get_profile(profile)
    except ValueError as exc:
        return f"Error: {exc}"
    return resolve_config(
        provider=provider,
        model=model,
        incremental=incremental,
        api_key=api_key,
        profile=profile,
        diagrams=diagrams,
    )


def _inline_docs_section(output_dir: str) -> str:
    """Render generated docs inline (for remote callers), capped by MAX_INLINE_DOC_KB."""
    try:
        cap_kb = int(os.getenv("MAX_INLINE_DOC_KB", "300"))
    except ValueError:
        cap_kb = 300
    budget = cap_kb * 1024
    lines = ["\n\n## Generated Documentation Files\n"]
    skipped = 0
    for root, _dirs, files in sorted(os.walk(output_dir)):
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(root, fname), output_dir)
            try:
                with open(os.path.join(root, fname), "r", encoding="utf-8") as fh:
                    content = fh.read()
            except OSError:
                continue
            block = f"\n### `{rel}`\n\n{content}\n"
            if len(block.encode("utf-8")) > budget:
                skipped += 1
                continue
            budget -= len(block.encode("utf-8"))
            lines.append(block)
    if skipped:
        lines.append(
            f"\n> {skipped} file(s) omitted — response capped at {cap_kb} KB "
            "(MAX_INLINE_DOC_KB). Use `push_as_pr=True` to receive everything.\n"
        )
    return "".join(lines)


mcp = FastMCP(
    "AI Document Creator",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_parse_allowed_hosts(),
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


def _load_existing_doc(file_path: str, output_dir: str) -> str | None:
    doc_path = os.path.join(output_dir, file_path + ".md")
    try:
        with open(doc_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


async def _run_pipeline(
    source: Source, output_dir: str, config: DocConfig, ctx: Context | None
) -> str:
    try:
        repo_path = source.prepare()
        all_files = list(
            FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse()
        )
        if not all_files:
            return "No files found to document."

        abs_output_dir = os.path.abspath(output_dir)

        if config.incremental:
            manifest = load_manifest(abs_output_dir)
            changed_files, unchanged_files = filter_changed(all_files, repo_path, manifest)
        else:
            changed_files, unchanged_files = list(all_files), []

        if not changed_files:
            n = len(unchanged_files)
            return (
                "# Documentation Up to Date\n\n"
                f"All {n} file{'s are' if n != 1 else ' is'} unchanged"
                " — no regeneration needed.\n"
            )

        # BYOK_ONLY: the server's env keys are never spent on requests. A
        # request carrying its own key keeps it (used explicitly, never via
        # env); anything else drops to host sampling / a clear error.
        if _BYOK_ONLY and not config.api_key:
            effective_config = DocConfig()
        else:
            effective_config = config
        backend = pick_backend(effective_config, ctx=ctx)

        final_state = await workflow_app.ainvoke(
            {
                "repo_path": repo_path,
                "files": changed_files,
                "documents": {},
                "index_content": "",
                "backend": backend,
                "max_concurrency": config.max_concurrency,
                "profile": config.profile,
                "diagrams": config.diagrams,
            }
        )

        if unchanged_files:
            all_docs: dict[str, str] = {}
            for fp in unchanged_files:
                existing = _load_existing_doc(fp, abs_output_dir)
                if existing is not None:
                    all_docs[fp] = existing
            all_docs.update(final_state["documents"])
            idx = await _generate_index(
                {
                    "repo_path": repo_path,
                    "files": list(all_docs.keys()),
                    "documents": all_docs,
                    "index_content": "",
                    "backend": backend,
                    "max_concurrency": config.max_concurrency,
                    "profile": config.profile,
                    "diagrams": config.diagrams,
                }
            )
            index_content = idx["index_content"]
            docs_to_write = final_state["documents"]
        else:
            index_content = final_state["index_content"]
            docs_to_write = final_state["documents"]

        DocumentationWriter(abs_output_dir).write_docs(docs_to_write, index_content)
        save_manifest(compute_hashes(all_files, repo_path), abs_output_dir)

        num_changed = len(docs_to_write)
        num_unchanged = len(unchanged_files)
        return (
            "# Documentation Generation Report\n\n"
            f"- **Files Processed**: {len(changed_files)}\n"
            f"- **Unchanged (skipped)**: {num_unchanged}\n"
            f"- **Documentation Pages Created**: {num_changed}\n"
            f"- **Local Output Path**: `{abs_output_dir}`\n\n"
            "## Generated README.md Content\n\n"
            "```markdown\n"
            f"{index_content}\n"
            "```\n"
        )
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        return f"Error occurred: {exc}"
    finally:
        source.cleanup()


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _parse_github_slug(repo_url: str) -> tuple[str, str]:
    match = re.search(
        r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url
    )
    if not match:
        raise ValueError(f"Cannot parse GitHub owner/repo from URL: {repo_url}")
    return match.group(1), match.group(2)


async def _push_docs_pr(
    repo_url: str,
    docs_dir: str,
    branch: str,
    title: str,
    github_token: str,
) -> str:
    """Commit generated docs to a branch on GitHub and open a PR. Returns PR URL."""
    loop = asyncio.get_running_loop()

    def _sync() -> str:
        owner, repo_name = _parse_github_slug(repo_url)
        gh = Github(github_token)
        gh_repo = gh.get_repo(f"{owner}/{repo_name}")
        default_branch = gh_repo.default_branch
        base_sha = gh_repo.get_branch(default_branch).commit.sha

        try:
            gh_repo.create_git_ref(f"refs/heads/{branch}", base_sha)
        except GithubException as exc:
            if exc.status != 422:  # 422 = branch already exists
                raise

        commit_message = "docs: add AI-generated documentation"
        for fname in os.listdir(docs_dir):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(docs_dir, fname), "r", encoding="utf-8") as fh:
                content = fh.read()
            target = f"docs/{fname}"
            try:
                existing = gh_repo.get_contents(target, ref=branch)
                # get_contents returns ContentFile | list[ContentFile];
                # for a single file path it is always a single object.
                if isinstance(existing, list):
                    existing = existing[0]
                gh_repo.update_file(
                    target, commit_message, content, existing.sha, branch=branch
                )
            except GithubException as exc:
                if exc.status == 404:
                    gh_repo.create_file(target, commit_message, content, branch=branch)
                else:
                    raise

        pr = gh_repo.create_pull(
            title=title,
            body=(
                "Auto-generated documentation by "
                "[AI Document Creator]"
                "(https://github.com/dharmikraval1/ai-document-creator)."
            ),
            head=branch,
            base=default_branch,
        )
        return pr.html_url

    try:
        return await loop.run_in_executor(None, _sync)
    except Exception as exc:
        logger.error("PR push failed: %s", exc)
        return f"PR push failed: {exc}"


@mcp.tool()
async def document_local_project(
    path: str = ".",
    output_dir: str = "docs",
    provider: str | None = None,
    model: str | None = None,
    incremental: bool = True,
    profile: str = "readme",
    diagrams: bool = True,
    ctx: Context | None = None,
) -> str:
    """Generate documentation for a project folder on the local machine.

    Args:
        path: Path to the local project directory.
        output_dir: Where to write the generated markdown files.
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama). Auto-detected
            from env if omitted; falls back to host sampling when no key is configured.
        model: Model name override (uses provider default when omitted).
        incremental: Skip unchanged files using content-hash caching.
        profile: Documentation style: readme (default), api, architecture, or tutorial.
        diagrams: Include Mermaid architecture/dependency diagrams and per-file
            flow charts where helpful.
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_local_project started path=%s", path)

    if _is_remote() and not os.getenv("LOCAL_ROOT", "").strip():
        return _LOCAL_TOOL_DISABLED_MSG

    try:
        validate_local_path(path)
        validate_local_path(output_dir)
    except ValueError as exc:
        return f"Error: {exc}"

    config = _resolve_request_config(provider, model, incremental, ctx, profile, diagrams)
    if isinstance(config, str):
        return config
    async with _pipeline_semaphore:
        try:
            return await asyncio.wait_for(
                _run_pipeline(LocalSource(path), output_dir, config, ctx),
                timeout=config.pipeline_timeout_s,
            )
        except asyncio.TimeoutError:
            return (
                f"Error: pipeline timed out after {config.pipeline_timeout_s}s. "
                "The project may be too large or the LLM provider is unresponsive."
            )


@mcp.tool()
async def document_repo(
    repo_url: str,
    output_dir: str = "docs",
    github_token: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    incremental: bool = True,
    profile: str = "readme",
    diagrams: bool = True,
    push_as_pr: bool = False,
    pr_branch: str | None = None,
    pr_title: str | None = None,
    return_docs: bool = False,
    ctx: Context | None = None,
) -> str:
    """Generate documentation for a GitHub repository (clones it first).

    Args:
        repo_url: HTTPS URL of the repository to document.
        output_dir: Where to write the generated markdown files (ignored on
            hosted deployments — docs go to a temp dir; use return_docs or
            push_as_pr to receive them).
        github_token: Token for private repos (falls back to GITHUB_TOKEN env var).
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama).
        model: Model name override.
        incremental: Skip unchanged files using content-hash caching.
        profile: Documentation style: readme (default), api, architecture, or tutorial.
        diagrams: Include Mermaid architecture/dependency diagrams and per-file
            flow charts where helpful.
        push_as_pr: If True, commit the generated docs to a branch and open a PR.
        pr_branch: Branch name (default: docs/ai-generated-{timestamp}).
        pr_title: PR title (default: "docs: AI-generated documentation").
        return_docs: If True, include the generated markdown files inline in
            the response (size-capped by MAX_INLINE_DOC_KB).
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_repo started url=%s push_as_pr=%s", repo_url, push_as_pr)

    try:
        validate_repo_url(repo_url)
    except ValueError as exc:
        return f"Error: {exc}"

    # Remote callers must not choose server filesystem paths: write to a fresh
    # per-request temp dir instead. No prior manifest exists there, so
    # incremental caching is meaningless remotely — disable it.
    remote = _is_remote()
    tmp_root: str | None = None
    if remote:
        tmp_root = tempfile.mkdtemp(prefix="ai-doc-out-")
        effective_output = os.path.join(tmp_root, "docs")
        incremental = False
    else:
        effective_output = output_dir

    config = _resolve_request_config(provider, model, incremental, ctx, profile, diagrams)
    if isinstance(config, str):
        return config

    try:
        async with _pipeline_semaphore:
            try:
                report = await asyncio.wait_for(
                    _run_pipeline(
                        # Remote callers never inherit the server's GITHUB_TOKEN:
                        # they must send their own for private repos.
                        GitSource(
                            repo_url,
                            github_token=github_token,
                            use_env_token=not remote,
                        ),
                        effective_output,
                        config,
                        ctx,
                    ),
                    timeout=config.pipeline_timeout_s,
                )
            except asyncio.TimeoutError:
                return (
                    f"Error: pipeline timed out after {config.pipeline_timeout_s}s. "
                    "The repository may be too large or the LLM provider is unresponsive."
                )

        if push_as_pr and not report.startswith("Error"):
            # Same rule as cloning: the server's own GITHUB_TOKEN is never
            # spent on behalf of remote callers.
            token = github_token or (None if remote else os.getenv("GITHUB_TOKEN"))
            if not token:
                report += (
                    "\n\nWarning: `push_as_pr=True` was requested but no GitHub token is "
                    "available — skipping PR creation. Pass `github_token` with permission "
                    "to open pull requests on the repository."
                )
            else:
                pr_url = await _push_docs_pr(
                    repo_url=repo_url,
                    docs_dir=os.path.abspath(effective_output),
                    branch=pr_branch or f"docs/ai-generated-{_timestamp()}",
                    title=pr_title or "docs: AI-generated documentation",
                    github_token=token,
                )
                report += f"\n\n## Pull Request\n\n{pr_url}"

        if return_docs and not report.startswith("Error") and os.path.isdir(effective_output):
            report += _inline_docs_section(os.path.abspath(effective_output))

        return report
    finally:
        if tmp_root is not None:
            import shutil

            shutil.rmtree(tmp_root, ignore_errors=True)


@mcp.tool()
async def check_doc_drift(
    path: str = ".",
    output_dir: str = "docs",
) -> str:
    """Report which source files have changed since the last documentation run.

    Reads the content-hash manifest written by a previous documentation run and
    compares it against the current file hashes.  No LLM calls are made.

    Args:
        path: Path to the local project directory (same value used when generating docs).
        output_dir: Directory where docs were generated (must contain the manifest).
    """
    if _is_remote() and not os.getenv("LOCAL_ROOT", "").strip():
        return _LOCAL_TOOL_DISABLED_MSG

    try:
        validate_local_path(path)
        validate_local_path(output_dir)
    except ValueError as exc:
        return f"Error: {exc}"

    abs_output_dir = os.path.abspath(output_dir)
    manifest = load_manifest(abs_output_dir)
    if manifest is None:
        return (
            "# Documentation Drift Check\n\n"
            "No manifest found — run `document_local_project` first to establish a baseline.\n"
        )

    try:
        all_files = list(FileTraverser(path, max_file_size_kb=None).traverse())
    except Exception as exc:
        return f"Error traversing {path}: {exc}"

    changed, unchanged = filter_changed(all_files, path, manifest)

    new_files = [f for f in changed if f not in manifest]
    modified = [f for f in changed if f in manifest]
    deleted = [f for f in manifest if f not in set(all_files)]

    lines = ["# Documentation Drift Check\n"]
    if not changed and not deleted:
        lines.append("All files are up to date — no drift detected.\n")
    else:
        if new_files:
            lines.append(f"## New Files ({len(new_files)})\n")
            lines.extend(f"- `{f}`" for f in sorted(new_files))
            lines.append("")
        if modified:
            lines.append(f"## Modified Files ({len(modified)})\n")
            lines.extend(f"- `{f}`" for f in sorted(modified))
            lines.append("")
        if deleted:
            lines.append(f"## Deleted Files ({len(deleted)})\n")
            lines.extend(f"- `{f}`" for f in sorted(deleted))
            lines.append("")
        lines.append(
            "Run `document_local_project` with `incremental=True` to update the documentation.\n"
        )

    return "\n".join(lines)


# --- Host-driven documentation jobs ------------------------------------------
# Zero-API-key path for MCP clients WITHOUT sampling support (Claude Code,
# Cursor, Codex, ...): the server hands source files to the host's own model
# as tool results; the model writes the docs and submits them back.


@mcp.tool()
async def start_doc_job(
    repo_url: str | None = None,
    path: str | None = None,
    output_dir: str = "docs",
    github_token: str | None = None,
    profile: str = "readme",
    diagrams: bool = True,
    ctx: Context | None = None,
) -> str:
    """Start a documentation job where YOU (the calling model) write the docs.

    Use this when no API key is configured and your client does not support
    MCP sampling. Flow: start_doc_job → get_next_files → write markdown for
    each file → submit_docs → repeat until none remain → finish_doc_job.

    Args:
        repo_url: HTTPS GitHub URL to document (exactly one of repo_url/path).
        path: Local project directory (stdio installs only).
        output_dir: Where finish_doc_job writes markdown (local runs only).
        github_token: Token for private repos.
        profile: readme (default), api, architecture, or tutorial.
        diagrams: Append Mermaid structure/dependency diagrams at finish.
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    if (repo_url is None) == (path is None):
        return "Error: provide exactly one of repo_url or path."
    try:
        get_profile(profile)
    except ValueError as exc:
        return f"Error: {exc}"

    remote = _is_remote()
    source: Source
    if path is not None:
        if remote and not os.getenv("LOCAL_ROOT", "").strip():
            return _LOCAL_TOOL_DISABLED_MSG
        try:
            validate_local_path(path)
            validate_local_path(output_dir)
        except ValueError as exc:
            return f"Error: {exc}"
        source = LocalSource(path)
    else:
        assert repo_url is not None
        try:
            validate_repo_url(repo_url)
        except ValueError as exc:
            return f"Error: {exc}"
        source = GitSource(repo_url, github_token=github_token, use_env_token=not remote)

    try:
        repo_path = source.prepare()
        config = resolve_config()
        files = list(
            FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse()
        )
    except Exception as exc:
        source.cleanup()
        return f"Error: {exc}"
    if not files:
        source.cleanup()
        return "No files found to document."

    job = DocJob(
        job_id=new_job_id(),
        repo_path=repo_path,
        source=source,
        pending=sorted(files),
        profile=profile,
        diagrams=diagrams,
        remote=remote,
        output_dir=output_dir,
        repo_url=repo_url,
    )
    try:
        _job_store.create(job)
    except JobError as exc:
        source.cleanup()
        return f"Error: {exc}"
    logger.info("doc job %s started files=%d remote=%s", job.job_id, job.total, remote)
    return (
        "# Documentation Job Started\n\n"
        f"- **job_id**: `{job.job_id}`\n"
        f"- **files**: {job.total}\n"
        f"- **profile**: {profile}\n\n"
        "You will write the documentation yourself, batch by batch.\n\n"
        f'NEXT: call `get_next_files(job_id="{job.job_id}")`.'
    )


@mcp.tool()
async def get_next_files(job_id: str, max_files: int = 3) -> str:
    """Get the next batch of source files to document for a running job.

    Write markdown documentation for EACH returned file following the
    included template, then call submit_docs with your docs.

    Args:
        job_id: Id returned by start_doc_job.
        max_files: Max files in this batch (1-10; large files ride alone).
    """
    try:
        job = _job_store.get(job_id)
    except JobError as exc:
        return f"Error: {exc}"
    if not job.pending:
        if job.sent:
            return (
                f"No new files; {len(job.sent)} handed-out file(s) still await docs: "
                + ", ".join(f"`{f}`" for f in sorted(job.sent))
                + f'\n\nNEXT: call `submit_docs(job_id="{job_id}", docs={{...}})`.'
            )
        return (
            "All files are documented.\n\n"
            f'NEXT: call `finish_doc_job(job_id="{job_id}", index_markdown="<the README '
            'you write summarizing the whole project>")`.'
        )

    max_files = max(1, min(10, max_files))
    prof = get_profile(job.profile)
    batch: list[tuple[str, str]] = []
    budget = _JOB_BATCH_BYTES
    while job.pending and len(batch) < max_files:
        file_path = job.pending[0]
        try:
            with open(
                os.path.join(job.repo_path, file_path), "r", encoding="utf-8", errors="ignore"
            ) as fh:
                content = fh.read()
        except OSError as exc:
            # Unreadable file: record the failure as its doc so the job can finish.
            job.pending.pop(0)
            job.docs[file_path] = f"Error reading file: {exc}"
            continue
        if batch and len(content.encode("utf-8")) > budget:
            break  # keep oversized file for its own batch
        job.pending.pop(0)
        job.sent.add(file_path)
        budget -= len(content.encode("utf-8"))
        batch.append((file_path, content))

    if not batch:
        return (
            "All files are documented.\n\n"
            f'NEXT: call `finish_doc_job(job_id="{job_id}", index_markdown="...")`.'
        )

    parts = [
        f"# Files to Document ({len(batch)} in this batch, {job.remaining - len(batch)} more after)\n",
        "Write markdown documentation for EACH file below with these sections:\n",
        prof.file_sections,
    ]
    for file_path, content in batch:
        parts.append(f"\n## FILE: {file_path}\n\n```\n{content}\n```\n")
    parts.append(
        f'\nNEXT: call `submit_docs(job_id="{job_id}", '
        'docs={"<file_path>": "<markdown>", ...})` with one entry per file above.'
    )
    return "".join(parts)


@mcp.tool()
async def submit_docs(job_id: str, docs: dict[str, str]) -> str:
    """Submit the markdown documentation you wrote for handed-out files.

    Args:
        job_id: Id returned by start_doc_job.
        docs: Mapping of file_path (exactly as given by get_next_files) to
            the markdown documentation you wrote for it.
    """
    try:
        job = _job_store.get(job_id)
    except JobError as exc:
        return f"Error: {exc}"
    if not docs:
        return "Error: docs is empty — pass {file_path: markdown} for handed-out files."
    unknown = [f for f in docs if f not in job.sent and f not in job.pending]
    if unknown:
        return (
            "Error: not part of this job or already documented: "
            + ", ".join(f"`{f}`" for f in unknown)
            + ". Use file paths exactly as returned by get_next_files."
        )
    for file_path, markdown in docs.items():
        job.sent.discard(file_path)
        if file_path in job.pending:
            job.pending.remove(file_path)
        job.docs[file_path] = sanitize_mermaid_blocks(markdown)

    done, total = len(job.docs), job.total
    if job.remaining:
        return (
            f"Stored {len(docs)} doc(s) — {done}/{total} done.\n\n"
            f'NEXT: call `get_next_files(job_id="{job_id}")`.'
        )
    return (
        f"Stored {len(docs)} doc(s) — all {total} files documented.\n\n"
        f'NEXT: call `finish_doc_job(job_id="{job_id}", index_markdown="<the README you '
        'write summarizing the whole project from the docs you produced>")`.'
    )


@mcp.tool()
async def finish_doc_job(
    job_id: str,
    index_markdown: str | None = None,
    push_as_pr: bool = False,
    github_token: str | None = None,
    pr_branch: str | None = None,
    pr_title: str | None = None,
    return_docs: bool | None = None,
) -> str:
    """Finalize a documentation job: write/return the docs (and optionally open a PR).

    Args:
        job_id: Id returned by start_doc_job.
        index_markdown: The project README you wrote (recommended). A simple
            table of contents is generated when omitted. Architecture diagrams
            are appended automatically.
        push_as_pr: Commit the docs to a branch of the source repo and open a PR.
        github_token: Token for push_as_pr (remote callers must supply their own).
        pr_branch: Branch name (default docs/ai-generated-{timestamp}).
        pr_title: PR title (default "docs: AI-generated documentation").
        return_docs: Inline all docs in the response. Defaults to True on the
            hosted endpoint (where there is no other way to receive them).
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    try:
        job = _job_store.get(job_id)
    except JobError as exc:
        return f"Error: {exc}"
    if job.remaining:
        return (
            f"Error: {job.remaining} file(s) still need docs "
            f"({len(job.pending)} pending, {len(job.sent)} handed out).\n\n"
            f'NEXT: call `get_next_files(job_id="{job_id}")` and keep going.'
        )

    if index_markdown and index_markdown.strip():
        index = sanitize_mermaid_blocks(index_markdown)
    else:
        index = "# Documentation Index\n\n" + "\n".join(
            f"- [`{f}`]({f}.md)" for f in sorted(job.docs)
        )
    if job.diagrams:
        index += build_diagram_section(sorted(job.docs), job.repo_path)

    if return_docs is None:
        return_docs = job.remote

    tmp_root: str | None = None
    try:
        if job.remote:
            tmp_root = tempfile.mkdtemp(prefix="ai-doc-out-")
            effective_output = os.path.join(tmp_root, "docs")
        else:
            effective_output = job.output_dir
        abs_output = os.path.abspath(effective_output)
        DocumentationWriter(abs_output).write_docs(job.docs, index)

        report = (
            "# Documentation Job Complete\n\n"
            f"- **Files documented**: {len(job.docs)}\n"
            + ("" if job.remote else f"- **Local Output Path**: `{abs_output}`\n")
        )

        if push_as_pr and job.repo_url:
            token = github_token or (None if job.remote else os.getenv("GITHUB_TOKEN"))
            if not token:
                report += (
                    "\nWarning: `push_as_pr=True` was requested but no GitHub token is "
                    "available — skipping PR creation. Pass `github_token`.\n"
                )
            else:
                pr_url = await _push_docs_pr(
                    repo_url=job.repo_url,
                    docs_dir=abs_output,
                    branch=pr_branch or f"docs/ai-generated-{_timestamp()}",
                    title=pr_title or "docs: AI-generated documentation",
                    github_token=token,
                )
                report += f"\n## Pull Request\n\n{pr_url}\n"
        elif push_as_pr:
            report += "\nWarning: push_as_pr only applies to jobs started with repo_url.\n"

        if return_docs:
            report += _inline_docs_section(abs_output)
        logger.info("doc job %s finished files=%d", job_id, len(job.docs))
        return report
    except Exception as exc:
        logger.error("doc job %s finish failed: %s", job_id, exc)
        return f"Error occurred: {exc}"
    finally:
        _job_store.remove(job_id)
        if tmp_root is not None:
            import shutil

            shutil.rmtree(tmp_root, ignore_errors=True)


def build_http_app(transport: str = "both"):
    """Starlette app for HTTP serving.

    transport: "streamable-http" (spec-current, at /mcp), "sse" (legacy, at
    /sse + /messages/), or "both" (default) — streamable-http plus the SSE
    routes so pre-migration clients of the hosted endpoint keep working.
    """
    if transport == "sse":
        app = mcp.sse_app()
    else:
        # The streamable-http app owns the session-manager lifespan; adding the
        # SSE routes onto it (rather than mounting two apps) keeps that intact.
        app = mcp.streamable_http_app()
        if transport == "both":
            existing = {getattr(r, "path", None) for r in app.routes}
            for route in mcp.sse_app().routes:
                if getattr(route, "path", None) not in existing:
                    app.router.routes.append(route)
    app.add_middleware(RateLimitMiddleware)
    return app


def main() -> None:
    port_env = os.getenv("PORT")
    if port_env:
        import uvicorn

        transport = os.getenv("MCP_TRANSPORT", "both").strip().lower() or "both"
        logger.info(
            "Starting MCP server in HTTP mode on port %s (transport=%s)",
            port_env,
            transport,
        )
        uvicorn.run(build_http_app(transport), host="0.0.0.0", port=int(port_env))
    else:
        logger.info("Starting MCP server in stdio mode")
        mcp.run()


if __name__ == "__main__":
    main()
