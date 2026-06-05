# core/sources.py
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import tempfile
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


def mask_token(url: str) -> str:
    """Replace any 'user:pass@' / 'token@' credential in a URL with '***'."""
    return re.sub(r"://[^@/]+@", "://***@", url)


class Source(ABC):
    """Provides a local filesystem root containing the project to document."""

    @abstractmethod
    def prepare(self) -> str:
        """Make the project available locally and return its root path."""

    def cleanup(self) -> None:
        """Release any temporary resources. Default: nothing to do."""


class LocalSource(Source):
    """A project that already lives on disk (stdio / local-agent use case)."""

    def __init__(self, path: str):
        self._path = os.path.abspath(path)

    def prepare(self) -> str:
        if not os.path.isdir(self._path):
            raise FileNotFoundError(f"Local path is not a directory: {self._path}")
        return self._path


class GitSource(Source):
    """Clones a Git repository into a temp dir and cleans it up afterwards."""

    def __init__(self, repo_url: str, github_token: str | None = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.temp_dir = tempfile.mkdtemp()
        self.repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        self.repo_url = self._authenticated_url(repo_url, self.github_token)

    def _authenticated_url(self, url: str, token: str | None) -> str:
        if not token or "@" in url:
            return url
        if url.startswith("https://"):
            return f"https://{token}@{url[len('https://'):]}"
        if url.startswith("http://"):
            return f"http://{token}@{url[len('http://'):]}"
        return url

    def prepare(self) -> str:
        from git import Repo

        logger.info("Cloning %s to %s", mask_token(self.repo_url), self.temp_dir)
        try:
            Repo.clone_from(self.repo_url, self.temp_dir)
            return self.temp_dir
        except Exception:
            self.cleanup()
            raise

    def cleanup(self) -> None:
        if not os.path.exists(self.temp_dir):
            return

        def _on_error(func, path, _exc):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        shutil.rmtree(self.temp_dir, onerror=_on_error)
