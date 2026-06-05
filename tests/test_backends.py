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


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    def __init__(self, *args, **kwargs):
        self.invoked_with = None

    async def ainvoke(self, prompt):
        self.invoked_with = prompt
        return _FakeMessage("GENERATED")


async def test_provider_backend_invokes_model(monkeypatch):
    import core.backends as backends

    captured = {}

    def fake_init(model=None, model_provider=None, **kwargs):
        captured["model"] = model
        captured["model_provider"] = model_provider
        return _FakeModel()

    monkeypatch.setattr(backends, "init_chat_model", fake_init)

    from core.config import DocConfig
    backend = backends.ProviderBackend(DocConfig(provider="anthropic"))
    out = await backend.complete("hi")

    assert out == "GENERATED"
    assert captured["model_provider"] == "anthropic"
    assert captured["model"] == "claude-sonnet-4-6"


def test_provider_backend_requires_model():
    from core.backends import BackendError, ProviderBackend
    from core.config import DocConfig
    with __import__("pytest").raises(BackendError):
        ProviderBackend(DocConfig())  # no provider -> no model_id
