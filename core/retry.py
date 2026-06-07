# core/retry.py
from __future__ import annotations

import logging

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .backends import BackendError, CompletionBackend

logger = logging.getLogger(__name__)


def with_retry(
    backend: CompletionBackend,
    max_attempts: int = 3,
    _wait=None,
) -> CompletionBackend:
    """Return a backend whose ``complete()`` retries on transient failures.

    *_wait* is a tenacity wait strategy; it defaults to exponential backoff
    and exists solely so tests can pass ``wait_none()`` for instant retries.
    """
    return _RetryBackend(backend, max_attempts=max_attempts, _wait=_wait)


class _RetryBackend(CompletionBackend):
    def __init__(self, inner: CompletionBackend, max_attempts: int, _wait=None) -> None:
        wait_strategy = (
            _wait
            if _wait is not None
            else wait_exponential(multiplier=1, min=1, max=8)
        )

        @retry(
            retry=retry_if_not_exception_type((BackendError, ValueError, TypeError)),
            stop=stop_after_attempt(max_attempts),
            wait=wait_strategy,
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _run(prompt: str) -> str:
            return await inner.complete(prompt)

        self._run = _run

    async def complete(self, prompt: str) -> str:
        return await self._run(prompt)
