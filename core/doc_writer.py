import os
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class DocumentationWriter:
    """Writes generated documentation to files."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def write_docs(self, documents: Dict[str, str], index_content: str):
        """Writes the documentation files and the index file."""
        try:
            # Create output directory if it doesn't exist
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Write individual file docs
            for file_path, content in documents.items():
                # We want to mirror the structure inside the output dir
                # e.g., src/main.py -> docs/src/main.py.md
                
                relative_path = file_path + ".md"
                full_path = os.path.join(self.output_dir, relative_path)
                
                # Ensure the directory for this file exists
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                logger.info(f"Written documentation for {file_path} to {full_path}")

            # Write index file
            index_path = os.path.join(self.output_dir, "README.md")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(index_content)
            logger.info(f"Written index to {index_path}")
            
        except Exception as e:
            logger.error(f"Failed to write documentation: {e}")
            raise
