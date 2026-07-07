# mcp_server_impl.py — back-compat shim; the server lives in ai_doc_creator.server.
# Keeps existing deployments (CMD ["python", "mcp_server_impl.py"]) working.
from ai_doc_creator.server import main, mcp  # noqa: F401

if __name__ == "__main__":
    main()
