# tests/test_config.py
import pytest

from core.config import DocConfig, detect_provider, resolve_config

_CRED_ENVS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AWS_ACCESS_KEY_ID"]


@pytest.fixture
def clean_provider_env(monkeypatch):
    """Clear all provider credential env vars so detection tests are deterministic."""
    for var in _CRED_ENVS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_model_id_uses_default_model_when_only_provider_given():
    cfg = DocConfig(provider="anthropic")
    assert cfg.model_id == "anthropic:claude-sonnet-4-6"


def test_model_id_uses_explicit_model():
    cfg = DocConfig(provider="openai", model="gpt-4o-mini")
    assert cfg.model_id == "openai:gpt-4o-mini"


def test_model_id_is_none_without_provider():
    assert DocConfig().model_id is None
    assert DocConfig().has_provider is False


def test_lc_provider_maps_known_providers():
    assert DocConfig(provider="azure").lc_provider == "azure_openai"
    assert DocConfig(provider="bedrock").lc_provider == "bedrock_converse"
    assert DocConfig(provider=None).lc_provider is None


def test_lc_provider_passthrough_for_unknown():
    assert DocConfig(provider="custom_llm").lc_provider == "custom_llm"


def test_resolved_model_azure_returns_none():
    # azure has no default model; the deployment name is supplied separately at backend build time
    assert DocConfig(provider="azure").resolved_model is None


def test_resolved_model_explicit_overrides_default():
    assert DocConfig(provider="anthropic", model="claude-x").resolved_model == "claude-x"


def test_detect_provider_reads_env(clean_provider_env):
    clean_provider_env.setenv("OPENAI_API_KEY", "sk-test")
    assert detect_provider() == "openai"


def test_detect_provider_priority_prefers_anthropic(clean_provider_env):
    clean_provider_env.setenv("ANTHROPIC_API_KEY", "a")
    clean_provider_env.setenv("OPENAI_API_KEY", "o")
    assert detect_provider() == "anthropic"


def test_detect_provider_none_when_no_creds(clean_provider_env):
    assert detect_provider() is None


def test_resolve_config_prefers_explicit_provider(clean_provider_env):
    clean_provider_env.setenv("OPENAI_API_KEY", "sk-test")
    cfg = resolve_config(provider="ollama", model="llama3.1", profile="onboarding")
    assert cfg.provider == "ollama"
    assert cfg.profile == "onboarding"


def test_resolve_config_accepts_falsy_overrides():
    cfg = resolve_config(provider="anthropic", incremental=False, diagrams=False, max_file_size_kb=0)
    assert cfg.incremental is False
    assert cfg.diagrams is False
    assert cfg.max_file_size_kb == 0


def test_resolve_config_rejects_unknown_kwarg():
    with pytest.raises(TypeError):
        resolve_config(provider="anthropic", model_id="boom")


def test_pipeline_timeout_defaults_to_300():
    cfg = DocConfig()
    assert cfg.pipeline_timeout_s == 300


def test_resolve_config_reads_pipeline_timeout_from_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_TIMEOUT_S", "120")
    cfg = resolve_config()
    assert cfg.pipeline_timeout_s == 120
