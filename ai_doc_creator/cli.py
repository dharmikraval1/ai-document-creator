# ai_doc_creator/cli.py
import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from .core.config import resolve_config  # noqa: E402
from .core.backends import pick_backend, BackendError  # noqa: E402
from .core.sources import GitSource, LocalSource  # noqa: E402
from .core.file_traverser import FileTraverser  # noqa: E402
from .core.graph import app  # noqa: E402
from .core.doc_writer import DocumentationWriter  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def run(source, output_dir, config):
    repo_path = None
    try:
        repo_path = source.prepare()
        files = list(FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse())
        logger.info("Found %d files to process.", len(files))
        if not files:
            logger.warning("No files found to document. Exiting.")
            return

        backend = pick_backend(config, ctx=None)  # CLI has no host -> requires a provider key
        final_state = await app.ainvoke(
            {
                "repo_path": repo_path,
                "files": files,
                "documents": {},
                "index_content": "",
                "backend": backend,
                "max_concurrency": config.max_concurrency,
            }
        )

        DocumentationWriter(output_dir).write_docs(
            final_state["documents"], final_state["index_content"]
        )
        logger.info("Documentation generation complete!")
    finally:
        if source:
            source.cleanup()


def main():
    parser = argparse.ArgumentParser(description="AI Document Creator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", help="GitHub repository URL")
    group.add_argument("--path", help="Local project directory")
    parser.add_argument("--output", default="docs", help="Output directory")
    parser.add_argument(
        "--provider", default=None, help="LLM provider (anthropic/openai/azure/bedrock/ollama)"
    )
    parser.add_argument("--model", default=None, help="Model name override")
    args = parser.parse_args()

    config = resolve_config(provider=args.provider, model=args.model)
    source = GitSource(args.repo) if args.repo else LocalSource(args.path)

    try:
        asyncio.run(run(source, args.output, config))
    except BackendError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("An error occurred: %s", exc)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
