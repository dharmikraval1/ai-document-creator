# core/backends.py
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from langchain.chat_models import init_chat_model  # imported at top so tests can monkeypatch it

from .config import DocConfig


class BackendError(RuntimeError):
    """Raised when no usable LLM backend can be constructed."""


def _content_to_text(content) -> str:
    """Flatten a chat model response (str, or list of content blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


class CompletionBackend(ABC):
    """Generates text from a prompt. The only thing the pipeline knows about an LLM."""

    @abstractmethod
    async def complete(self, prompt: str) -> str: ...


class FakeBackend(CompletionBackend):
    """Deterministic backend for tests — never calls a real model."""

    def __init__(self, response: str = "FAKE DOC"):
        self.response = response
        self.calls: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


class ProviderBackend(CompletionBackend):
    """Calls a real provider (anthropic/openai/azure/bedrock/ollama) via LangChain."""

    def __init__(self, config: DocConfig):
        if not config.has_provider:
            raise BackendError("ProviderBackend requires a provider")
        if config.provider == "azure":
            self._model = self._build_azure(config)
        else:
            # Pass model + provider separately so model names containing ':'
            # (e.g. bedrock 'amazon.nova-pro-v1:0') are never mis-parsed.
            # An explicit per-request key (BYOK) wins over any env credential.
            extra: dict = {}
            if config.api_key:
                extra["api_key"] = config.api_key
            self._model = init_chat_model(
                model=config.resolved_model,
                model_provider=config.lc_provider,
                temperature=0,
                **extra,
            )

    @staticmethod
    def _build_azure(config: DocConfig):
        from langchain_openai import AzureChatOpenAI

        from pydantic import SecretStr

        raw_key = config.api_key or os.getenv("AZURE_OPENAI_API_KEY")
        return AzureChatOpenAI(
            azure_deployment=config.model or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=SecretStr(raw_key) if raw_key else None,
            temperature=0,
        )

    async def complete(self, prompt: str) -> str:
        result = await self._model.ainvoke(prompt)
        return _content_to_text(getattr(result, "content", result))


class SamplingBackend(CompletionBackend):
    """Asks the MCP host's own model to generate — zero API cost to the operator."""

    def __init__(self, ctx, max_tokens: int = 4096):
        self._ctx = ctx
        self._max_tokens = max_tokens

    async def complete(self, prompt: str) -> str:
        from mcp.types import SamplingMessage, TextContent

        try:
            result = await self._ctx.session.create_message(
                messages=[
                    SamplingMessage(role="user", content=TextContent(type="text", text=prompt))
                ],
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            # A client that never serves sampling answers with JSON-RPC
            # "Method not found" (-32601). Translate the protocol noise into
            # the actionable error users need.
            code = getattr(getattr(exc, "error", None), "code", None)
            if code == -32601 or "method not found" in str(exc).lower():
                raise BackendError(_NO_SAMPLING_MSG) from exc
            raise
        content = result.content
        return content.text if getattr(content, "type", None) == "text" else str(content)


_NO_SAMPLING_MSG = (
    "This MCP client does not support sampling, so the server has no model to "
    "write with. Provide an API key instead: send the X-Provider-API-Key header "
    "(hosted endpoint) or set a provider key such as ANTHROPIC_API_KEY / "
    "OPENAI_API_KEY (local install), or pass provider='ollama' for a local model."
)


def _client_supports_sampling(ctx) -> bool:
    """True when the connected MCP client declared the sampling capability.

    Unknown session shapes (tests, exotic SDKs) return True so the request
    still tries sampling and surfaces any failure through SamplingBackend's
    own error translation.
    """
    try:
        from mcp.types import ClientCapabilities, SamplingCapability

        return bool(
            ctx.session.check_client_capability(
                ClientCapabilities(sampling=SamplingCapability())
            )
        )
    except Exception:
        return True


def pick_backend(config: DocConfig, ctx=None) -> CompletionBackend:
    """Choose a backend: provider key → retry-wrapped ProviderBackend;
    MCP host ctx with sampling support → SamplingBackend; otherwise raise
    BackendError.
    """
    from .retry import with_retry

    if config.has_provider:
        return with_retry(ProviderBackend(config))
    if ctx is not None:
        if _client_supports_sampling(ctx):
            return SamplingBackend(ctx)
        raise BackendError(_NO_SAMPLING_MSG)
    raise BackendError(
        "No LLM available. Set a provider key (ANTHROPIC_API_KEY / OPENAI_API_KEY / "
        "AZURE_OPENAI_API_KEY / AWS credentials), pass provider='ollama' for a local model, "
        "or run inside an MCP host that supports sampling."
    )
