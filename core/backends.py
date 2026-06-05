# core/backends.py
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from langchain.chat_models import init_chat_model  # imported at top so tests can monkeypatch it

from .config import DocConfig


class BackendError(RuntimeError):
    """Raised when no usable LLM backend can be constructed."""


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
