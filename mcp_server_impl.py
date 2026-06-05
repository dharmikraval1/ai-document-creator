# mcp_server_impl.py
from dotenv import load_dotenv
import os
import sys

# Load env before importing core (provider keys are read during backend construction).
load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from core.config import resolve_config
from core.backends import pick_backend
from core.sources import GitSource, LocalSource
from core.file_traverser import FileTraverser
from core.graph import app as workflow_app
from core.doc_writer import DocumentationWriter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "AI Document Creator",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _run_pipeline(source, output_dir, config, ctx):
    """Shared flow: prepare source -> traverse -> generate -> write -> report."""
    repo_path = None
    try:
        repo_path = source.prepare()
        files = list(FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse())
        if not files:
            return "No files found to document."

        backend = pick_backend(config, ctx=ctx)
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
        logger.error("Error generating documentation: %s", exc)
        return f"Error occurred: {exc}"
    finally:
        if source:
            source.cleanup()


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
        output_dir: Where to write the generated markdown.
        provider: Optional LLM provider (anthropic/openai/azure/bedrock/ollama). If omitted,
            uses an env-configured provider, else the host model via sampling.
        model: Optional model name to override the provider default.
    """
    config = resolve_config(provider=provider, model=model)
    return await _run_pipeline(LocalSource(path), output_dir, config, ctx)


@mcp.tool()
async def document_repo(
    repo_url: str,
    output_dir: str = "docs",
    github_token: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    ctx: Context = None,
) -> str:
    """Generate documentation for a GitHub repository (clones it first).

    Args:
        repo_url: URL of the repository to document.
        output_dir: Where to write the generated markdown.
        github_token: Token for private repos (falls back to GITHUB_TOKEN env).
        provider: Optional LLM provider (anthropic/openai/azure/bedrock/ollama).
        model: Optional model name to override the provider default.
    """
    config = resolve_config(provider=provider, model=model)
    return await _run_pipeline(GitSource(repo_url, github_token=github_token), output_dir, config, ctx)


if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        logger.info("Starting MCP server in SSE mode on port %s", port_env)
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port_env)
        mcp.run(transport="sse")
    else:
        logger.info("Starting MCP server in Stdio mode")
        mcp.run()
