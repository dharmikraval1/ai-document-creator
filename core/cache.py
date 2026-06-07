# core/cache.py
from __future__ import annotations

import hashlib
import json
import os

MANIFEST_FILENAME = ".ai-docs-manifest.json"


def hash_file(repo_path: str, file_path: str) -> str:
    """Return the SHA-256 hex digest of the content of *repo_path/file_path*."""
    full = os.path.join(repo_path, file_path)
    h = hashlib.sha256()
    with open(full, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_hashes(files: list[str], repo_path: str) -> dict[str, str]:
    """Return ``{relative_path: sha256}`` for every path in *files*."""
    return {fp: hash_file(repo_path, fp) for fp in files}


def load_manifest(output_dir: str) -> dict[str, str] | None:
    """Load the hash manifest from *output_dir*.

    Returns ``None`` when no manifest exists or the file is corrupt.
    """
    path = os.path.join(output_dir, MANIFEST_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_manifest(file_hashes: dict[str, str], output_dir: str) -> None:
    """Persist *file_hashes* as ``{output_dir}/.ai-docs-manifest.json``."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, MANIFEST_FILENAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(file_hashes, fh, indent=2, sort_keys=True)


def filter_changed(
    files: list[str],
    repo_path: str,
    manifest: dict[str, str] | None,
) -> tuple[list[str], list[str]]:
    """Split *files* into ``(changed, unchanged)`` relative to *manifest*.

    All files are returned as changed when *manifest* is ``None`` (first run).
    Files that cannot be read are treated as changed.
    """
    if manifest is None:
        return list(files), []
    changed: list[str] = []
    unchanged: list[str] = []
    for fp in files:
        try:
            current_hash = hash_file(repo_path, fp)
        except OSError:
            changed.append(fp)
            continue
        if manifest.get(fp) == current_hash:
            unchanged.append(fp)
        else:
            changed.append(fp)
    return changed, unchanged
