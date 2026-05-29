from dotenv import load_dotenv
import os
import sys
# Load env vars before importing core modules specifically because core.graph initializes LLM at module level
load_dotenv()

# Add the current directory to sys.path so we can import from core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import logging
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from core.repo_loader import RepoLoader
from core.file_traverser import FileTraverser
from core.graph import app as workflow_app
from core.doc_writer import DocumentationWriter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create the MCP server with DNS rebinding protection disabled
# to permit external access through Render/Cloudflare proxies.
mcp = FastMCP(
    "AI Document Creator",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)

@mcp.tool()
async def document_repo(repo_url: str, output_dir: str = "docs") -> str:
    """
    Generates documentation for a GitHub repository.
    
    Args:
        repo_url: The URL of the GitHub repository to document.
        output_dir: The directory where the documentation should be saved. Defaults to "docs".
    """
    logger.info(f"Received request to document {repo_url} into {output_dir}")
    
    repo_loader = RepoLoader(repo_url)
    repo_path = None
    
    try:
        # 1. Clone Repo
        logger.info(f"Cloning repository: {repo_url}")
        repo_path = repo_loader.clone_repo()
        
        # 2. Traverse Files
        logger.info("Traversing files...")
        traverser = FileTraverser(repo_path)
        files = list(traverser.traverse())
        
        if not files:
            return "No files found to document."

        # 3. Process with LangGraph
        logger.info("Generating documentation...")
        initial_state = {
            "repo_path": repo_path,
            "files": files,
            "documents": {},
            "index_content": ""
        }
        
        final_state = await workflow_app.ainvoke(initial_state)
        
        # 4. Write Output
        # Ensure absolute path for output_dir if needed, but for now we trust the input
        # Note: In a real MCP server, we might want to be careful about where we write.
        abs_output_dir = os.path.abspath(output_dir)
        
        logger.info(f"Writing documentation to {abs_output_dir}")
        writer = DocumentationWriter(abs_output_dir)
        writer.write_docs(final_state["documents"], final_state["index_content"])
        
        return f"Documentation successfully generated in {abs_output_dir}"
        
    except Exception as e:
        logger.error(f"Error generating documentation: {e}")
        return f"Error occurred: {str(e)}"
    finally:
        if repo_loader:
            repo_loader.cleanup()

if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        logger.info(f"Starting MCP server in SSE mode on port {port_env}")
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port_env)
        mcp.run(transport="sse")
    else:
        logger.info("Starting MCP server in Stdio mode")
        mcp.run()
