# mcp_server_impl.py
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from github import Github, GithubException

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from core.config import DocConfig, resolve_config
from core.backends import pick_backend
from core.guards import validate_local_path, validate_repo_url
from core.logging_config import REQUEST_ID_VAR, setup_logging
from core.sources import GitSource, LocalSource, Source
from core.file_traverser import FileTraverser
from core.graph import app as workflow_app
from core.doc_writer import DocumentationWriter

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


async def _run_pipeline(source: Source, output_dir: str, config: DocConfig, ctx: Context | None) -> str:
    try:
        repo_path = source.prepare()
        files = list(
            FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse()
        )
        if not files:
            return "No files found to document."

        effective_config = DocConfig() if _BYOK_ONLY else config
        backend = pick_backend(effective_config, ctx=ctx)

        final_state = await workflow_app.ainvoke(
            {
                "repo_path": repo_path,
                "files": files,
                "documents": {},
                "index_content": "",
                "backend": backend,
                "max_concurrency": config.max_concurrency,
            }
        )

        abs_output_dir = os.path.abspath(output_dir)
        DocumentationWriter(abs_output_dir).write_docs(
            final_state["documents"], final_state["index_content"]
        )

        num_docs = len(final_state.get("documents", {}))
        return (
            "# Documentation Generation Report\n\n"
            f"- **Files Processed**: {len(files)}\n"
            f"- **Documentation Pages Created**: {num_docs}\n"
            f"- **Local Output Path**: `{abs_output_dir}`\n\n"
            "## Generated README.md Content\n\n"
            "```markdown\n"
            f"{final_state.get('index_content', '')}\n"
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
    ctx: Context = None,
) -> str:
    """Generate documentation for a project folder on the local machine.

    Args:
        path: Path to the local project directory.
        output_dir: Where to write the generated markdown files.
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama). Auto-detected
            from env if omitted; falls back to host sampling when no key is configured.
        model: Model name override (uses provider default when omitted).
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_local_project started path=%s", path)

    try:
        validate_local_path(path)
    except ValueError as exc:
        return f"Error: {exc}"

    config = resolve_config(provider=provider, model=model)
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
    push_as_pr: bool = False,
    pr_branch: str | None = None,
    pr_title: str | None = None,
    ctx: Context = None,
) -> str:
    """Generate documentation for a GitHub repository (clones it first).

    Args:
        repo_url: HTTPS URL of the repository to document.
        output_dir: Where to write the generated markdown files.
        github_token: Token for private repos (falls back to GITHUB_TOKEN env var).
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama).
        model: Model name override.
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

    config = resolve_config(provider=provider, model=model)
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
