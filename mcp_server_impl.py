# mcp_server_impl.py
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from github import Github, GithubException  # noqa: E402

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from core.config import DocConfig, resolve_config  # noqa: E402
from core.backends import pick_backend  # noqa: E402
from core.guards import validate_local_path, validate_repo_url  # noqa: E402
from core.logging_config import REQUEST_ID_VAR, setup_logging  # noqa: E402
from core.sources import GitSource, LocalSource, Source  # noqa: E402
from core.file_traverser import FileTraverser  # noqa: E402
from core.graph import app as workflow_app, generate_index as _generate_index  # noqa: E402
from core.doc_writer import DocumentationWriter  # noqa: E402
from core.cache import compute_hashes, filter_changed, load_manifest, save_manifest  # noqa: E402

setup_logging(json_mode=os.getenv("LOG_FORMAT", "").lower() == "json")
logger = logging.getLogger(__name__)

__version__ = "2.0.0"

_BYOK_ONLY: bool = os.getenv("BYOK_ONLY", "").lower() == "true"
_pipeline_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_PIPELINES", "3")))


def _parse_allowed_hosts() -> list[str]:
    raw = os.getenv(
        "MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,localhost:*,127.0.0.1:*"
    )
    return [h.strip() for h in raw.split(",") if h.strip()]


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

        effective_config = DocConfig() if _BYOK_ONLY else config
        backend = pick_backend(effective_config, ctx=ctx)

        final_state = await workflow_app.ainvoke(
            {
                "repo_path": repo_path,
                "files": changed_files,
                "documents": {},
                "index_content": "",
                "backend": backend,
                "max_concurrency": config.max_concurrency,
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
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_local_project started path=%s", path)

    try:
        validate_local_path(path)
    except ValueError as exc:
        return f"Error: {exc}"

    config = resolve_config(provider=provider, model=model, incremental=incremental)
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
    push_as_pr: bool = False,
    pr_branch: str | None = None,
    pr_title: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Generate documentation for a GitHub repository (clones it first).

    Args:
        repo_url: HTTPS URL of the repository to document.
        output_dir: Where to write the generated markdown files.
        github_token: Token for private repos (falls back to GITHUB_TOKEN env var).
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama).
        model: Model name override.
        incremental: Skip unchanged files using content-hash caching.
        push_as_pr: If True, commit the generated docs to a branch and open a PR.
        pr_branch: Branch name (default: docs/ai-generated-{timestamp}).
        pr_title: PR title (default: "docs: AI-generated documentation").
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_repo started url=%s push_as_pr=%s", repo_url, push_as_pr)

    try:
        validate_repo_url(repo_url)
    except ValueError as exc:
        return f"Error: {exc}"

    config = resolve_config(provider=provider, model=model, incremental=incremental)
    async with _pipeline_semaphore:
        try:
            report = await asyncio.wait_for(
                _run_pipeline(
                    GitSource(repo_url, github_token=github_token),
                    output_dir,
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
        token = github_token or os.getenv("GITHUB_TOKEN")
        if not token:
            report += (
                "\n\nWarning: `push_as_pr=True` was requested but no GitHub token is "
                "available — skipping PR creation."
            )
        else:
            pr_url = await _push_docs_pr(
                repo_url=repo_url,
                docs_dir=os.path.abspath(output_dir),
                branch=pr_branch or f"docs/ai-generated-{_timestamp()}",
                title=pr_title or "docs: AI-generated documentation",
                github_token=token,
            )
            report += f"\n\n## Pull Request\n\n{pr_url}"

    return report


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
    try:
        validate_local_path(path)
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


if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        logger.info("Starting MCP server in SSE mode on port %s", port_env)
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port_env)
        mcp.run(transport="sse")
    else:
        logger.info("Starting MCP server in stdio mode")
        mcp.run()
