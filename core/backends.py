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
            self._model = init_chat_model(
                model=config.resolved_model,
                model_provider=config.lc_provider,
                temperature=0,
            )

    @staticmethod
    def _build_azure(config: DocConfig):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=config.model or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
            openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
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

        result = await self._ctx.session.create_message(
            messages=[
                SamplingMessage(role="user", content=TextContent(type="text", text=prompt))
            ],
            max_tokens=self._max_tokens,
        )
        content = result.content
        return content.text if getattr(content, "type", None) == "text" else str(content)


def pick_backend(config: DocConfig, ctx=None) -> CompletionBackend:
    """Choose a backend: provider key → retry-wrapped ProviderBackend;
    MCP host ctx → SamplingBackend; otherwise raise BackendError.
    """
    from .retry import with_retry

    if config.has_provider:
        return with_retry(ProviderBackend(config))
    if ctx is not None:
        return SamplingBackend(ctx)
    raise BackendError(
        "No LLM available. Set a provider key (ANTHROPIC_API_KEY / OPENAI_API_KEY / "
        "AZURE_OPENAI_API_KEY / AWS credentials), pass provider='ollama' for a local model, "
        "or run inside an MCP host that supports sampling."
    )
