import argparse
import logging
import os
import sys
from dotenv import load_dotenv

# Load env vars before importing core modules specifically because core.graph initializes LLM at module level
load_dotenv()

# Add the current directory to sys.path so we can import from core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.repo_loader import RepoLoader
from core.file_traverser import FileTraverser
from core.graph import app
from core.doc_writer import DocumentationWriter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():

    
    parser = argparse.ArgumentParser(description="AI Document Creator")
    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument("--output", default="docs", help="Output directory for documentation")
    
    args = parser.parse_args()
    
    repo_loader = RepoLoader(args.repo)
    repo_path = None
    
    try:
        # 1. Clone Repo
        logger.info(f"Cloning repository: {args.repo}")
        repo_path = repo_loader.clone_repo()
        
        # 2. Traverse Files
        logger.info("Traversing files...")
        traverser = FileTraverser(repo_path)
        files = list(traverser.traverse())
        logger.info(f"Found {len(files)} files to process.")
        
        if not files:
            logger.warning("No files found to document. Exiting.")
            return

        # 3. Process with LangGraph
        logger.info("Generating documentation (this may take a while)...")
        initial_state = {
            "repo_path": repo_path,
            "files": files,
            "documents": {},
            "index_content": ""
        }
        
        final_state = app.invoke(initial_state)
        
        # 4. Write Output
        logger.info(f"Writing documentation to {args.output}")
        writer = DocumentationWriter(args.output)
        writer.write_docs(final_state["documents"], final_state["index_content"])
        
        logger.info("Documentation generation complete!")
        
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if repo_loader:
            repo_loader.cleanup()

if __name__ == "__main__":
    main()
