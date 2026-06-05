# core/config.py
from __future__ import annotations

import os
from dataclasses import dataclass

# Default model per provider (overridable via the `model` field / env).
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "azure": None,  # azure uses AZURE_OPENAI_DEPLOYMENT_NAME, not a model string
    "bedrock": "amazon.nova-pro-v1:0",
    "ollama": "llama3.1",
}

# Friendly provider name -> LangChain `init_chat_model` provider id.
LC_PROVIDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "azure": "azure_openai",
    "bedrock": "bedrock_converse",
    "ollama": "ollama",
}

# Env var whose presence means "this provider's credentials are available".
# ollama is local and needs no key, so it is never auto-detected (must be explicit).
_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
}


@dataclass
class DocConfig:
    provider: str | None = None
    model: str | None = None
    profile: str = "readme"
    incremental: bool = True
    diagrams: bool = True
    max_file_size_kb: int = 100
    max_concurrency: int = 8

    @property
    def has_provider(self) -> bool:
        return self.provider is not None

    @property
    def model_id(self) -> str | None:
        """Human-readable id for logging, e.g. 'anthropic:claude-sonnet-4-6'."""
        if not self.provider:
            return None
        model = self.model or DEFAULT_MODELS.get(self.provider)
        return f"{self.provider}:{model}" if model else self.provider

    @property
    def lc_provider(self) -> str | None:
        """The provider id understood by LangChain `init_chat_model`."""
        return LC_PROVIDER.get(self.provider, self.provider) if self.provider else None

    @property
    def resolved_model(self) -> str | None:
        """The concrete model name (explicit override or provider default)."""
        if not self.provider:
            return None
        return self.model or DEFAULT_MODELS.get(self.provider)


def detect_provider() -> str | None:
    """Return the first provider whose credentials are present in the environment."""
    for provider, env_var in _PROVIDER_ENV.items():
        if os.getenv(env_var):
            return provider
    return None


def resolve_config(provider: str | None = None, model: str | None = None, **overrides) -> DocConfig:
    """Build a DocConfig, auto-detecting the provider from env when not given."""
    cfg = DocConfig(provider=provider or detect_provider(), model=model)
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
