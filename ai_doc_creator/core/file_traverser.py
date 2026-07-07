import os
import fnmatch
from typing import Generator, List, Optional


class FileTraverser:
    """Traverses a directory and yields file paths, filtering out ignored files."""

    def __init__(
        self,
        root_dir: str,
        ignore_patterns: Optional[List[str]] = None,
        max_file_size_kb: int = 100,
    ):
        self.root_dir = root_dir
        self.max_file_size_kb = max_file_size_kb
        self.ignore_patterns = ignore_patterns or [
            ".git", ".venv", "__pycache__", "*.pyc", "*.pyo", "*.pyd", ".DS_Store",
            "node_modules", "dist", "build", "*.egg-info", ".idea", ".vscode"
        ]

    def _is_ignored(self, path: str) -> bool:
        """Checks if a file or directory path matches any ignore pattern."""
        name = os.path.basename(path)
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _is_binary(self, file_path: str) -> bool:
        """Checks if a file is binary by extension or null-byte detection."""
        binary_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar', '.gz',
            '.db', '.sqlite', '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4',
            '.wav', '.avi', '.mov', '.webp', '.exe', '.dll', '.so', '.dylib',
            '.class', '.jar', '.war', '.ear', '.svg'
        }
        _, ext = os.path.splitext(file_path.lower())
        if ext in binary_extensions:
            return True

        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                if b'\x00' in chunk:
                    return True
        except Exception:
            return True
        return False

    def traverse(self) -> Generator[str, None, None]:
        """Yields file paths relative to root_dir with forward slash separators."""
        for root, dirs, files in os.walk(self.root_dir):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if not self._is_ignored(os.path.join(root, d))]

            for file in files:
                file_path = os.path.join(root, file)
                if self._is_ignored(file_path):
                    continue

                # Check file size
                try:
                    size_kb = os.path.getsize(file_path) / 1024
                    if size_kb > self.max_file_size_kb:
                        continue
                except Exception:
                    continue

                # Check if binary
                if self._is_binary(file_path):
                    continue

                # Yield relative path normalized with forward slashes
                rel_path = os.path.relpath(file_path, self.root_dir)
                yield rel_path.replace(os.sep, '/')
