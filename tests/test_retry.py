# tests/test_retry.py
import pytest
from tenacity import wait_none

from ai_doc_creator.core.backends import BackendError, CompletionBackend, FakeBackend
from ai_doc_creator.core.retry import with_retry


class _FailNTimes(CompletionBackend):
    """Fails the first *n* calls, then returns *then_return*."""

    def __init__(self, n: int, then_return: str = "OK"):
        self.calls = 0
        self._n = n
        self._then = then_return

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        if self.calls <= self._n:
            raise RuntimeError(f"transient error #{self.calls}")
        return self._then


async def test_retries_and_succeeds_after_transient_failures():
    inner = _FailNTimes(n=2)
    backend = with_retry(inner, max_attempts=3, _wait=wait_none())
    result = await backend.complete("hello")
    assert result == "OK"
    assert inner.calls == 3


async def test_raises_after_exhausting_attempts():
    inner = _FailNTimes(n=99)
    backend = with_retry(inner, max_attempts=3, _wait=wait_none())
    with pytest.raises(RuntimeError, match="transient error"):
        await backend.complete("hello")
    assert inner.calls == 3


async def test_does_not_retry_backend_error():
    class _BadConfig(CompletionBackend):
        async def complete(self, prompt: str) -> str:
            raise BackendError("config error")

    backend = with_retry(_BadConfig(), max_attempts=3, _wait=wait_none())
    with pytest.raises(BackendError):
        await backend.complete("hello")


async def test_does_not_retry_value_error():
    class _BadInput(CompletionBackend):
        async def complete(self, prompt: str) -> str:
            raise ValueError("bad input")

    backend = with_retry(_BadInput(), max_attempts=3, _wait=wait_none())
    with pytest.raises(ValueError):
        await backend.complete("hello")


async def test_wrapped_backend_is_a_completion_backend():
    assert isinstance(with_retry(FakeBackend(), _wait=wait_none()), CompletionBackend)
