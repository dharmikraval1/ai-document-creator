# ai_doc_creator/core/jobs.py
"""In-memory store for host-driven documentation jobs.

A job hands source files to the MCP *client's* model batch by batch and
collects the docs it writes back — the zero-API-key path for hosts that do
not implement MCP sampling. State is per-process: a job must finish on the
instance that started it (documented limitation, mirrors the rate limiter).
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class JobError(ValueError):
    """User-facing job problem (unknown/expired id, wrong state, limits)."""


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class DocJob:
    job_id: str
    repo_path: str
    source: Any                      # Source; cleanup() releases clone temp dirs
    pending: list[str]               # files not yet handed to the host
    sent: set[str] = field(default_factory=set)   # handed out, awaiting docs
    docs: dict[str, str] = field(default_factory=dict)
    profile: str = "readme"
    diagrams: bool = True
    remote: bool = False
    output_dir: str = "docs"
    repo_url: str | None = None
    created_at: float = field(default_factory=time.monotonic)

    @property
    def total(self) -> int:
        return len(self.pending) + len(self.sent) + len(self.docs)

    @property
    def remaining(self) -> int:
        return len(self.pending) + len(self.sent)


class JobStore:
    def __init__(self, max_jobs: int | None = None, ttl_s: float | None = None):
        self._jobs: dict[str, DocJob] = {}
        self.max_jobs = max_jobs if max_jobs is not None else _int_env("MAX_DOC_JOBS", 20)
        self.ttl_s = ttl_s if ttl_s is not None else _int_env("DOC_JOB_TTL_S", 1800)

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - self.ttl_s
        for job_id in [j for j, job in self._jobs.items() if job.created_at <= cutoff]:
            self.remove(job_id)

    def create(self, job: DocJob) -> None:
        self._purge_expired()
        if len(self._jobs) >= self.max_jobs:
            raise JobError(
                f"Too many active documentation jobs ({self.max_jobs}); "
                "finish or let existing jobs expire first."
            )
        self._jobs[job.job_id] = job

    def get(self, job_id: str) -> DocJob:
        self._purge_expired()
        job = self._jobs.get(job_id)
        if job is None:
            raise JobError(
                f"Unknown or expired job id '{job_id}'. Start again with start_doc_job."
            )
        return job

    def remove(self, job_id: str) -> None:
        job = self._jobs.pop(job_id, None)
        if job is not None:
            try:
                job.source.cleanup()
            except Exception:
                pass

    def __len__(self) -> int:
        return len(self._jobs)


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
