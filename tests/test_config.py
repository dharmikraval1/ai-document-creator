# tests/test_config.py
from core.config import DocConfig, detect_provider, resolve_config


def test_model_id_uses_default_model_when_only_provider_given():
    cfg = DocConfig(provider="anthropic")
    assert cfg.model_id == "anthropic:claude-sonnet-4-6"


def test_model_id_uses_explicit_model():
    cfg = DocConfig(provider="openai", model="gpt-4o-mini")
    assert cfg.model_id == "openai:gpt-4o-mini"


def test_model_id_is_none_without_provider():
    assert DocConfig().model_id is None
    assert DocConfig().has_provider is False


def test_detect_provider_reads_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert detect_provider() == "openai"


def test_resolve_config_prefers_explicit_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = resolve_config(provider="ollama", model="llama3.1", profile="onboarding")
    assert cfg.provider == "ollama"
    assert cfg.profile == "onboarding"
