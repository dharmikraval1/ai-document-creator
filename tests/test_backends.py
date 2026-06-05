# tests/test_backends.py
import pytest

from core.backends import CompletionBackend, FakeBackend


async def test_fake_backend_returns_canned_response_and_records_calls():
    backend = FakeBackend("HELLO DOCS")
    out = await backend.complete("document this")
    assert out == "HELLO DOCS"
    assert backend.calls == ["document this"]


def test_fake_backend_is_a_completion_backend():
    assert isinstance(FakeBackend(), CompletionBackend)
