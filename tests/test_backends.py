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
        ProviderBackend(DocConfig())  # no provider -> has_provider is False


class _FakeSession:
    def __init__(self):
        self.received = None

    async def create_message(self, messages, max_tokens):
        self.received = {"messages": messages, "max_tokens": max_tokens}

        class _Text:
            type = "text"
            text = "SAMPLED DOC"

        class _Result:
            content = _Text()

        return _Result()


class _FakeCtx:
    def __init__(self):
        self.session = _FakeSession()


async def test_sampling_backend_calls_host_session():
    from core.backends import SamplingBackend
    ctx = _FakeCtx()
    backend = SamplingBackend(ctx, max_tokens=256)
    out = await backend.complete("document this file")
    assert out == "SAMPLED DOC"
    assert ctx.session.received["max_tokens"] == 256


async def test_pick_backend_prefers_provider_when_key_present(monkeypatch):
    import core.backends as backends
    monkeypatch.setattr(backends, "init_chat_model", lambda *a, **k: _FakeModel())
    from core.config import DocConfig
    backend = backends.pick_backend(DocConfig(provider="openai"), ctx=_FakeCtx())
    assert isinstance(backend, backends.CompletionBackend)
    assert not isinstance(backend, backends.SamplingBackend)


def test_pick_backend_falls_back_to_sampling_with_ctx():
    from core.backends import pick_backend, SamplingBackend
    from core.config import DocConfig
    backend = pick_backend(DocConfig(), ctx=_FakeCtx())
    assert isinstance(backend, SamplingBackend)


def test_pick_backend_raises_clear_error_without_provider_or_ctx():
    import pytest
    from core.backends import pick_backend, BackendError
    from core.config import DocConfig
    with pytest.raises(BackendError) as exc:
        pick_backend(DocConfig(), ctx=None)
    assert "provider key" in str(exc.value)


async def test_provider_backend_flattens_list_content(monkeypatch):
    import core.backends as backends

    class _ListModel:
        async def ainvoke(self, prompt):
            return _FakeMessage([{"type": "text", "text": "A"}, {"type": "text", "text": "B"}])

    monkeypatch.setattr(backends, "init_chat_model", lambda **k: _ListModel())
    from core.config import DocConfig
    backend = backends.ProviderBackend(DocConfig(provider="anthropic"))
    assert await backend.complete("hi") == "AB"


async def test_provider_backend_ignores_non_text_blocks(monkeypatch):
    import core.backends as backends

    class _MixedModel:
        async def ainvoke(self, prompt):
            return _FakeMessage([{"type": "text", "text": "keep"}, {"type": "image", "source": "x"}])

    monkeypatch.setattr(backends, "init_chat_model", lambda **k: _MixedModel())
    from core.config import DocConfig
    backend = backends.ProviderBackend(DocConfig(provider="anthropic"))
    assert await backend.complete("hi") == "keep"


async def test_provider_backend_azure_branch(monkeypatch):
    import langchain_openai
    from core.config import DocConfig
    from core.backends import ProviderBackend

    captured = {}

    class _FakeAzure:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def ainvoke(self, prompt):
            return _FakeMessage("AZURE OUT")

    monkeypatch.setattr(langchain_openai, "AzureChatOpenAI", _FakeAzure)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)

    backend = ProviderBackend(DocConfig(provider="azure"))
    assert captured["azure_deployment"] == "gpt-4o"  # falls back to default when env unset
    assert await backend.complete("hi") == "AZURE OUT"


async def test_sampling_backend_non_text_falls_back_to_str():
    from core.backends import SamplingBackend

    class _Img:
        type = "image"

        def __str__(self):
            return "IMG-BLOCK"

    class _Result:
        content = _Img()

    class _Sess:
        async def create_message(self, messages, max_tokens):
            return _Result()

    class _Ctx:
        session = _Sess()

    out = await SamplingBackend(_Ctx()).complete("x")
    assert out == "IMG-BLOCK"
