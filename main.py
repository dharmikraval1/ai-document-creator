# main.py — back-compat shim; the CLI lives in ai_doc_creator.cli.
from ai_doc_creator.cli import main

if __name__ == "__main__":
    main()
