# core/config.py
from __future__ import annotations

import os
from dataclasses import dataclass, fields

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "azure": None,
    "bedrock": "amazon.nova-pro-v1:0",
    "ollama": "llama3.1",
}

LC_PROVIDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "azure": "azure_openai",
    "bedrock": "bedrock_converse",
    "ollama": "ollama",
}

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
    pipeline_timeout_s: int = 300

    @property
    def has_provider(self) -> bool:
        return self.provider is not None

    @property
    def model_id(self) -> str | None:
        if not self.provider:
            return None
        model = self.model or DEFAULT_MODELS.get(self.provider)
        return f"{self.provider}:{model}" if model else self.provider

    @property
    def lc_provider(self) -> str | None:
        return LC_PROVIDER.get(self.provider, self.provider) if self.provider else None

    @property
    def resolved_model(self) -> str | None:
        if not self.provider:
            return None
        return self.model or DEFAULT_MODELS.get(self.provider)


def detect_provider() -> str | None:
    """Return the first provider whose credentials are present in the environment."""
    for provider, env_var in _PROVIDER_ENV.items():
        if os.getenv(env_var):
            return provider
    return None


def resolve_config(
    provider: str | None = None,
    model: str | None = None,
    **overrides,
) -> DocConfig:
    """Build a DocConfig, auto-detecting the provider from env when not given."""
    cfg = DocConfig(provider=provider or detect_provider(), model=model)
    timeout_env = os.getenv("PIPELINE_TIMEOUT_S")
    if timeout_env and timeout_env.isdigit():
        cfg.pipeline_timeout_s = int(timeout_env)
    valid_fields = {f.name for f in fields(DocConfig)}
    for key, value in overrides.items():
        if key not in valid_fields:
            raise TypeError(f"resolve_config() got an unexpected keyword argument '{key}'")
        if value is not None:
            setattr(cfg, key, value)
    return cfg
