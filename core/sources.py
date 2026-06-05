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
