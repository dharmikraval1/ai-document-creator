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
async def document_repo(
    repo_url: str,
    output_dir: str = "docs",
    push_to_repo: bool = False,
    github_token: str = None,
    commit_message: str = "docs: add AI-generated documentation and README.md"
) -> str:
    """
    Generates documentation for a GitHub repository.
    
    Args:
        repo_url: The URL of the GitHub repository to document.
        output_dir: The directory where the documentation should be saved locally. Defaults to "docs".
        push_to_repo: If True, commits and pushes the generated README.md and documentation directly back to the GitHub repository. Defaults to False.
        github_token: The GitHub Personal Access Token to authenticate git operations. Falls back to the GITHUB_TOKEN environment variable.
        commit_message: Custom commit message when pushing to repository. Defaults to "docs: add AI-generated documentation and README.md".
    """
    logger.info(f"Received request to document {repo_url} into {output_dir}")
    
    repo_loader = RepoLoader(repo_url, github_token=github_token)
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
        
        # 4. Write Output locally
        abs_output_dir = os.path.abspath(output_dir)
        logger.info(f"Writing documentation to {abs_output_dir}")
        writer = DocumentationWriter(abs_output_dir)
        writer.write_docs(final_state["documents"], final_state["index_content"])
        
        push_status = "Disabled"
        if push_to_repo:
            try:
                logger.info("Writing documentation to cloned repository for push...")
                # Write README.md to the root of the repo
                repo_readme_path = os.path.join(repo_path, "README.md")
                with open(repo_readme_path, "w", encoding="utf-8") as f:
                    f.write(final_state["index_content"])
                
                # Write individual file docs inside the cloned repo
                docs_dir_name = output_dir if not os.path.isabs(output_dir) else "docs"
                repo_docs_dir = os.path.join(repo_path, docs_dir_name)
                
                repo_writer = DocumentationWriter(repo_docs_dir)
                repo_writer.write_docs(final_state["documents"], final_state["index_content"])
                
                # Perform git operations
                from git import Repo
                repo = Repo(repo_path)
                
                # Configure Git user (required if not globally configured)
                with repo.config_writer() as git_config:
                    git_config.set_value("user", "name", "AI Document Creator")
                    git_config.set_value("user", "email", "ai-document-creator@example.com")
                
                # Add all changes
                repo.git.add(A=True)
                
                # Commit and push if dirty
                if repo.is_dirty():
                    repo.index.commit(commit_message)
                    logger.info("Committed changes, pushing to remote...")
                    repo.remotes.origin.push()
                    push_status = "Successfully committed and pushed to GitHub"
                else:
                    push_status = "No changes detected, repository is already up to date"
            except Exception as git_err:
                logger.error(f"Git push failed: {git_err}")
                push_status = f"Failed to push changes: {str(git_err)}"
        
        # 5. Build and return Markdown Report
        readme_content = final_state.get("index_content", "")
        num_docs = len(final_state.get("documents", {}))
        
        report = f"""# Documentation Generation Report

## Summary
- **Repository**: {repo_url}
- **Files Processed**: {len(files)} source files
- **Documentation Pages Created**: {num_docs}
- **Local Output Path**: `{abs_output_dir}`
- **GitHub Push Status**: {push_status}

---

## Generated README.md Content
Below is the full content of the generated `README.md` file. You can easily view, copy, or save it:

```markdown
{readme_content}
```
"""
        return report
        
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
