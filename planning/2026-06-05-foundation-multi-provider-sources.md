# Foundation: Multi-Provider Backends + Local/GitHub Sources — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the pipeline so documentation can come from any **source** (local path or GitHub clone) and be written by any **backend** (multi-provider key or host-LLM sampling), without breaking existing CLI/MCP behaviour.

**Architecture:** Two new abstraction modules — `core/sources.py` (where files come from) and `core/backends.py` (which LLM generates text) — sit on either side of an unchanged, now backend-agnostic LangGraph pipeline. A `core/config.py` resolves provider/model/options. The pipeline becomes `async` with a bounded semaphore for concurrency control.

**Tech Stack:** Python 3.12, LangChain v1 (`init_chat_model`), LangGraph 1.x, MCP SDK 1.27 (FastMCP + sampling), GitPython, pytest + pytest-asyncio.

> **Working directory:** All paths are relative to `ai_document_creator/` (the project's own git repo). Run every command from inside `ai_document_creator/`. All commits land in that repo.

---

## File Structure (Phase 1)

- Create: `core/config.py` — `DocConfig` dataclass + provider detection/resolution.
- Create: `core/backends.py` — `CompletionBackend` interface, `FakeBackend`, `ProviderBackend`, `SamplingBackend`, `pick_backend()`.
- Create: `core/sources.py` — `Source` interface, `LocalSource`, `GitSource` (replaces `RepoLoader`), `mask_token()`.
- Modify: `core/graph.py` — remove module-level LLM; async nodes; backend + concurrency from state.
- Modify: `main.py` — build config/source/backend; `asyncio.run(app.ainvoke(...))`.
- Modify: `mcp_server_impl.py` — inject `Context`; add `document_local_project` tool; use sources + `pick_backend`.
- Modify: `requirements.txt` — add `langchain-anthropic`, `langchain-ollama`, `pytest-asyncio`.
- Create: `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`, plus one test file per module.
- Delete (end): `core/repo_loader.py` once `GitSource` replaces it.

---

## Task 0: Test scaffolding & dependencies

**Files:**
- Modify: `requirements.txt`
- Create: `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Add dependencies to `requirements.txt`**

Append these lines to `requirements.txt`:

```
langchain-anthropic
langchain-ollama
pytest-asyncio
```

- [ ] **Step 2: Install them**

Run: `.venv/Scripts/python.exe -m pip install langchain-anthropic langchain-ollama pytest-asyncio`
Expected: `Successfully installed ...` (no errors).

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 4: Create `tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 5: Create `tests/conftest.py`** (put project root on `sys.path` so `import core.*` works)

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 6: Verify pytest runs (collects nothing yet)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `no tests ran` (exit code 5) — confirms config is valid.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini tests/__init__.py tests/conftest.py
git commit -m "test: add pytest scaffolding and provider dependencies"
```

---

## Task 1: `core/config.py` — provider resolution

**Files:**
- Create: `core/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.config'`.

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat: add DocConfig and provider resolution"
```

---

## Task 2: `core/backends.py` — interface + FakeBackend

**Files:**
- Create: `core/backends.py`
- Test: `tests/test_backends.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.backends'`.

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add core/backends.py tests/test_backends.py
git commit -m "feat: add CompletionBackend interface and FakeBackend"
```

---

## Task 3: `ProviderBackend` (multi-provider via init_chat_model)

**Files:**
- Modify: `core/backends.py`
- Test: `tests/test_backends.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_backends.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -k provider -v`
Expected: FAIL with `AttributeError: module 'core.backends' has no attribute 'ProviderBackend'`.

- [ ] **Step 3: Add `ProviderBackend` to `core/backends.py`**

Add after `FakeBackend`:

```python
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
        content = getattr(result, "content", result)
        return content if isinstance(content, str) else str(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -k provider -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add core/backends.py tests/test_backends.py
git commit -m "feat: add ProviderBackend for multi-provider LLM access"
```

---

## Task 4: `SamplingBackend` (host-LLM via MCP sampling)

**Files:**
- Modify: `core/backends.py`
- Test: `tests/test_backends.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_backends.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -k sampling -v`
Expected: FAIL with `ImportError: cannot import name 'SamplingBackend'`.

- [ ] **Step 3: Add `SamplingBackend` to `core/backends.py`**

Add after `ProviderBackend`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -k sampling -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add core/backends.py tests/test_backends.py
git commit -m "feat: add SamplingBackend for host-LLM generation"
```

---

## Task 5: `pick_backend()` selection logic

**Files:**
- Modify: `core/backends.py`
- Test: `tests/test_backends.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_backends.py`:

```python
async def test_pick_backend_prefers_provider_when_key_present(monkeypatch):
    import core.backends as backends
    monkeypatch.setattr(backends, "init_chat_model", lambda *a, **k: _FakeModel())
    from core.config import DocConfig
    backend = backends.pick_backend(DocConfig(provider="openai"), ctx=_FakeCtx())
    assert isinstance(backend, backends.ProviderBackend)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -k pick_backend -v`
Expected: FAIL with `ImportError: cannot import name 'pick_backend'`.

- [ ] **Step 3: Add `pick_backend` to `core/backends.py`**

Add at the end of the file:

```python
def pick_backend(config: DocConfig, ctx=None) -> CompletionBackend:
    """Choose a backend: a configured provider wins; otherwise host sampling; else error."""
    if config.has_provider:
        return ProviderBackend(config)
    if ctx is not None:
        return SamplingBackend(ctx)
    raise BackendError(
        "No LLM available. Set a provider key (ANTHROPIC_API_KEY / OPENAI_API_KEY / "
        "AZURE_OPENAI_API_KEY / AWS credentials), pass provider='ollama' for a local model, "
        "or run inside an MCP host that supports sampling."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -v`
Expected: PASS (all backend tests pass).

- [ ] **Step 5: Commit**

```bash
git add core/backends.py tests/test_backends.py
git commit -m "feat: add pick_backend selection (provider > sampling > error)"
```

---

## Task 6: `core/sources.py` — Source interface + LocalSource

**Files:**
- Create: `core/sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sources.py
import os

import pytest

from core.sources import LocalSource, Source, mask_token


def test_mask_token_hides_credentials():
    assert mask_token("https://ghp_secret@github.com/u/r.git") == "https://***@github.com/u/r.git"
    assert mask_token("https://github.com/u/r.git") == "https://github.com/u/r.git"


def test_local_source_returns_existing_dir(tmp_path):
    src = LocalSource(str(tmp_path))
    assert src.prepare() == os.path.abspath(str(tmp_path))
    src.cleanup()  # must not raise


def test_local_source_rejects_missing_dir(tmp_path):
    src = LocalSource(str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError):
        src.prepare()


def test_local_source_is_a_source():
    assert isinstance(LocalSource("."), Source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.sources'`.

- [ ] **Step 3: Write the implementation**

```python
# core/sources.py
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import tempfile
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


def mask_token(url: str) -> str:
    """Replace any 'user:pass@' / 'token@' credential in a URL with '***'."""
    return re.sub(r"://[^@/]+@", "://***@", url)


class Source(ABC):
    """Provides a local filesystem root containing the project to document."""

    @abstractmethod
    def prepare(self) -> str:
        """Make the project available locally and return its root path."""

    def cleanup(self) -> None:
        """Release any temporary resources. Default: nothing to do."""


class LocalSource(Source):
    """A project that already lives on disk (stdio / local-agent use case)."""

    def __init__(self, path: str):
        self._path = os.path.abspath(path)

    def prepare(self) -> str:
        if not os.path.isdir(self._path):
            raise FileNotFoundError(f"Local path is not a directory: {self._path}")
        return self._path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add core/sources.py tests/test_sources.py
git commit -m "feat: add Source interface, LocalSource, and token masking"
```

---

## Task 7: `GitSource` (replaces RepoLoader, with token masking)

**Files:**
- Modify: `core/sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_sources.py`:

```python
from core.sources import GitSource


def test_gitsource_injects_token():
    src = GitSource("https://github.com/user/repo", github_token="tok")
    assert src.repo_url == "https://tok@github.com/user/repo"
    src.cleanup()


def test_gitsource_handles_dot_git_and_existing_auth():
    a = GitSource("https://github.com/user/repo.git", github_token="tok")
    assert a.repo_url == "https://tok@github.com/user/repo.git"
    a.cleanup()
    b = GitSource("https://other@github.com/user/repo.git", github_token="new")
    assert b.repo_url == "https://other@github.com/user/repo.git"
    b.cleanup()


def test_gitsource_no_token_leaves_url_untouched():
    src = GitSource("https://github.com/user/repo.git", github_token=None)
    assert src.repo_url == "https://github.com/user/repo.git"
    src.cleanup()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -k gitsource -v`
Expected: FAIL with `ImportError: cannot import name 'GitSource'`.

- [ ] **Step 3: Add `GitSource` to `core/sources.py`**

Add at the end of the file:

```python
class GitSource(Source):
    """Clones a Git repository into a temp dir and cleans it up afterwards."""

    def __init__(self, repo_url: str, github_token: str | None = None):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.temp_dir = tempfile.mkdtemp()
        self.repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        self.repo_url = self._authenticated_url(repo_url, self.github_token)

    def _authenticated_url(self, url: str, token: str | None) -> str:
        if not token or "@" in url:
            return url
        if url.startswith("https://"):
            return f"https://{token}@{url[len('https://'):]}"
        if url.startswith("http://"):
            return f"http://{token}@{url[len('http://'):]}"
        return url

    def prepare(self) -> str:
        from git import Repo

        logger.info("Cloning %s to %s", mask_token(self.repo_url), self.temp_dir)
        try:
            Repo.clone_from(self.repo_url, self.temp_dir)
            return self.temp_dir
        except Exception:
            self.cleanup()
            raise

    def cleanup(self) -> None:
        if not os.path.exists(self.temp_dir):
            return

        def _on_error(func, path, _exc):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        shutil.rmtree(self.temp_dir, onerror=_on_error)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -v`
Expected: PASS (all source tests pass).

- [ ] **Step 5: Commit**

```bash
git add core/sources.py tests/test_sources.py
git commit -m "feat: add GitSource replacing RepoLoader, with masked logging"
```

---

## Task 8: Make `core/graph.py` backend-agnostic & async

**Files:**
- Modify: `core/graph.py` (full rewrite)
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph.py
import os


async def test_pipeline_generates_docs_and_index_with_fake_backend(tmp_path):
    # arrange a tiny repo
    (tmp_path / "a.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1  # {not a format placeholder}", encoding="utf-8")

    from core.backends import FakeBackend
    from core.graph import app

    state = {
        "repo_path": str(tmp_path),
        "files": ["a.py", "b.py"],
        "documents": {},
        "index_content": "",
        "backend": FakeBackend("### Summary\nMocked summary.\n### Overview\nbody"),
        "max_concurrency": 4,
    }

    result = await app.ainvoke(state)

    assert set(result["documents"].keys()) == {"a.py", "b.py"}
    assert "Mocked summary." in result["documents"]["a.py"]
    assert result["index_content"]  # index produced from summaries


async def test_pipeline_isolates_unreadable_file(tmp_path):
    from core.backends import FakeBackend
    from core.graph import app

    state = {
        "repo_path": str(tmp_path),
        "files": ["missing.py"],
        "documents": {},
        "index_content": "",
        "backend": FakeBackend("doc"),
        "max_concurrency": 2,
    }
    result = await app.ainvoke(state)
    assert "Error reading file" in result["documents"]["missing.py"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_graph.py -v`
Expected: FAIL — current `graph.py` builds an LLM at import time and has no `backend` in state (likely an import/KeyError or model-auth error).

- [ ] **Step 3: Rewrite `core/graph.py`**

Replace the entire file with:

```python
# core/graph.py
from __future__ import annotations

import asyncio
import os
import re
from typing import Dict, List, TypedDict

from langgraph.graph import END, StateGraph

from .backends import CompletionBackend


class AgentState(TypedDict):
    repo_path: str
    files: List[str]
    documents: Dict[str, str]
    index_content: str
    backend: CompletionBackend
    max_concurrency: int


def build_doc_prompt(file_path: str, code_content: str) -> str:
    # f-strings avoid str.format brace issues when code contains { }.
    return (
        "You are an expert technical writer. Generate comprehensive documentation "
        "for the following code file.\n\n"
        f"File Path: {file_path}\n\n"
        "Code Content:\n"
        f"{code_content}\n\n"
        "Output Format: Markdown\n\n"
        "Include these sections:\n"
        "### Summary\nA concise 1-2 sentence high-level summary.\n"
        "### Overview\nThe file's role and importance.\n"
        "### Key Classes and Functions\nMain classes/functions, params, returns, behavior.\n"
        "### Usage Examples\nHow to import and use it (if applicable).\n"
    )


def build_index_prompt(file_list: str, doc_summaries: str) -> str:
    return (
        "You are an expert technical writer. Generate a premium, comprehensive README.md "
        "for the following repository.\n\n"
        f"Repository Structure (Files):\n{file_list}\n\n"
        f"Generated Documentation Summaries:\n{doc_summaries}\n\n"
        "Output Format: Markdown\n\n"
        "Include: Project Title, Project Overview, Architecture & Key Components, "
        "Installation, Usage, and Running Tests."
    )


def _extract_summary(doc_content: str) -> str:
    match = re.search(r"### Summary\s*([\s\S]*?)(?=(?:##|###)|$)", doc_content, re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    cleaned = re.sub(r"#+\s+.*", "", doc_content).strip()
    cleaned = "\n".join(line for line in cleaned.splitlines() if line.strip())
    return cleaned[:200] + "..." if len(cleaned) > 200 else cleaned


async def analyze_repo(state: AgentState):
    return {"files": state["files"]}


async def generate_docs(state: AgentState):
    backend = state["backend"]
    repo_path = state["repo_path"]
    semaphore = asyncio.Semaphore(state.get("max_concurrency", 8))

    async def process(file_path: str):
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception as exc:
            return file_path, f"Error reading file: {exc}"
        prompt = build_doc_prompt(file_path, content)
        async with semaphore:
            try:
                return file_path, await backend.complete(prompt)
            except Exception as exc:
                return file_path, f"Error generating documentation: {exc}"

    results = await asyncio.gather(*(process(fp) for fp in state["files"]))
    return {"documents": dict(results)}


async def generate_index(state: AgentState):
    documents = state["documents"]
    summaries = "\n".join(
        f"- **{path}**: {_extract_summary(doc)}" for path, doc in documents.items()
    )
    prompt = build_index_prompt("\n".join(state["files"]), summaries)
    index_content = await state["backend"].complete(prompt)
    return {"index_content": index_content}


workflow = StateGraph(AgentState)
workflow.add_node("analyze_repo", analyze_repo)
workflow.add_node("generate_docs", generate_docs)
workflow.add_node("generate_index", generate_index)
workflow.set_entry_point("analyze_repo")
workflow.add_edge("analyze_repo", "generate_docs")
workflow.add_edge("generate_docs", "generate_index")
workflow.add_edge("generate_index", END)

app = workflow.compile()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_graph.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/graph.py tests/test_graph.py
git commit -m "refactor: make graph backend-agnostic and async with bounded concurrency"
```

---

## Task 9: Wire CLI + MCP server to sources & backends

**Files:**
- Modify: `main.py`
- Modify: `mcp_server_impl.py`
- Delete: `core/repo_loader.py`
- Test: `tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing test (local-project tool happy path with FakeBackend)**

```python
# tests/test_mcp_tools.py
import asyncio


def test_document_local_project_uses_fake_backend(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")

    import mcp_server_impl as server
    from core.backends import FakeBackend

    # Force a deterministic backend regardless of env/host.
    monkeypatch.setattr(server, "pick_backend", lambda config, ctx=None: FakeBackend(
        "### Summary\nA file.\n### Overview\nbody"
    ))

    out_dir = tmp_path / "out"
    result = asyncio.run(
        server.document_local_project(
            path=str(tmp_path),
            output_dir=str(out_dir),
            ctx=None,
        )
    )

    assert "Documentation Generation Report" in result
    assert (out_dir / "README.md").exists()
    assert (out_dir / "main.py.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL with `AttributeError: module 'mcp_server_impl' has no attribute 'document_local_project'`.

- [ ] **Step 3: Rewrite `mcp_server_impl.py`**

Replace the entire file with:

```python
# mcp_server_impl.py
from dotenv import load_dotenv
import os
import sys

# Load env before importing core (provider keys are read during backend construction).
load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from core.config import resolve_config
from core.backends import pick_backend
from core.sources import GitSource, LocalSource
from core.file_traverser import FileTraverser
from core.graph import app as workflow_app
from core.doc_writer import DocumentationWriter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "AI Document Creator",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _run_pipeline(source, output_dir, config, ctx):
    """Shared flow: prepare source -> traverse -> generate -> write -> report."""
    repo_path = None
    try:
        repo_path = source.prepare()
        files = list(FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse())
        if not files:
            return "No files found to document."

        backend = pick_backend(config, ctx=ctx)
        final_state = await workflow_app.ainvoke(
            {
                "repo_path": repo_path,
                "files": files,
                "documents": {},
                "index_content": "",
                "backend": backend,
                "max_concurrency": config.max_concurrency,
            }
        )

        abs_output_dir = os.path.abspath(output_dir)
        DocumentationWriter(abs_output_dir).write_docs(
            final_state["documents"], final_state["index_content"]
        )

        num_docs = len(final_state.get("documents", {}))
        return (
            "# Documentation Generation Report\n\n"
            f"- **Files Processed**: {len(files)}\n"
            f"- **Documentation Pages Created**: {num_docs}\n"
            f"- **Local Output Path**: `{abs_output_dir}`\n\n"
            "## Generated README.md Content\n\n"
            "```markdown\n"
            f"{final_state.get('index_content', '')}\n"
            "```\n"
        )
    except Exception as exc:
        logger.error("Error generating documentation: %s", exc)
        return f"Error occurred: {exc}"
    finally:
        if source:
            source.cleanup()


@mcp.tool()
async def document_local_project(
    path: str = ".",
    output_dir: str = "docs",
    provider: str = None,
    model: str = None,
    ctx: Context = None,
) -> str:
    """Generate documentation for a project folder on the local machine.

    Args:
        path: Path to the local project directory.
        output_dir: Where to write the generated markdown.
        provider: Optional LLM provider (anthropic/openai/azure/bedrock/ollama). If omitted,
            uses an env-configured provider, else the host model via sampling.
        model: Optional model name to override the provider default.
    """
    config = resolve_config(provider=provider, model=model)
    return await _run_pipeline(LocalSource(path), output_dir, config, ctx)


@mcp.tool()
async def document_repo(
    repo_url: str,
    output_dir: str = "docs",
    github_token: str = None,
    provider: str = None,
    model: str = None,
    ctx: Context = None,
) -> str:
    """Generate documentation for a GitHub repository (clones it first).

    Args:
        repo_url: URL of the repository to document.
        output_dir: Where to write the generated markdown.
        github_token: Token for private repos (falls back to GITHUB_TOKEN env).
        provider: Optional LLM provider (anthropic/openai/azure/bedrock/ollama).
        model: Optional model name to override the provider default.
    """
    config = resolve_config(provider=provider, model=model)
    return await _run_pipeline(GitSource(repo_url, github_token=github_token), output_dir, config, ctx)


if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        logger.info("Starting MCP server in SSE mode on port %s", port_env)
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port_env)
        mcp.run(transport="sse")
    else:
        logger.info("Starting MCP server in Stdio mode")
        mcp.run()
```

- [ ] **Step 4: Run the tool test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -v`
Expected: PASS (1 passed).

> Note: `push_to_repo` from the old server is intentionally dropped here; it returns as a **PR-based** push in the Phase 2 (Hardening) plan.

- [ ] **Step 5: Rewrite `main.py` to use the new abstractions**

Replace the entire file with:

```python
# main.py
import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.config import resolve_config
from core.backends import pick_backend
from core.sources import GitSource, LocalSource
from core.file_traverser import FileTraverser
from core.graph import app
from core.doc_writer import DocumentationWriter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def run(source, output_dir, config):
    repo_path = None
    try:
        repo_path = source.prepare()
        files = list(FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse())
        logger.info("Found %d files to process.", len(files))
        if not files:
            logger.warning("No files found to document. Exiting.")
            return

        backend = pick_backend(config, ctx=None)  # CLI has no host -> requires a provider key
        final_state = await app.ainvoke(
            {
                "repo_path": repo_path,
                "files": files,
                "documents": {},
                "index_content": "",
                "backend": backend,
                "max_concurrency": config.max_concurrency,
            }
        )

        DocumentationWriter(output_dir).write_docs(
            final_state["documents"], final_state["index_content"]
        )
        logger.info("Documentation generation complete!")
    finally:
        if source:
            source.cleanup()


def main():
    parser = argparse.ArgumentParser(description="AI Document Creator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", help="GitHub repository URL")
    group.add_argument("--path", help="Local project directory")
    parser.add_argument("--output", default="docs", help="Output directory")
    parser.add_argument("--provider", default=None, help="LLM provider (anthropic/openai/azure/bedrock/ollama)")
    parser.add_argument("--model", default=None, help="Model name override")
    args = parser.parse_args()

    config = resolve_config(provider=args.provider, model=args.model)
    source = GitSource(args.repo) if args.repo else LocalSource(args.path)

    try:
        asyncio.run(run(source, args.output, config))
    except Exception as exc:
        logger.error("An error occurred: %s", exc)
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Delete the obsolete `core/repo_loader.py`**

Run: `git rm core/repo_loader.py`
Expected: `rm 'core/repo_loader.py'`.

- [ ] **Step 7: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass.

- [ ] **Step 8: Smoke-test the CLI on this very repo with Ollama (optional, needs Ollama running) OR confirm the clear error without a key**

Run (no provider key, no host): `.venv/Scripts/python.exe main.py --path . --output /tmp/docs_smoke`
Expected: a `BackendError` message instructing the user to set a provider key — confirms `pick_backend` guards correctly.

- [ ] **Step 9: Commit**

```bash
git add main.py mcp_server_impl.py tests/test_mcp_tools.py
git commit -m "feat: wire CLI and MCP server to sources + multi-provider backends"
```

---

## Done criteria for Phase 1

- `.venv/Scripts/python.exe -m pytest -q` is green.
- `document_local_project` and `document_repo` both run through the same pipeline.
- No module-level LLM; backend is chosen per request (provider key → provider; else host sampling; else clear error).
- Tokens never appear unmasked in logs.
- `core/repo_loader.py` is gone; `GitSource` replaces it.

## What Phase 1 deliberately leaves for later plans

- **Phase 2 (Hardening):** SSRF/abuse guards, global concurrency cap, retries/timeouts, DNS-rebinding re-enable, `/health`, structured logging, PR-based push, repo flatten.
- **Phase 3:** `cache.py` incremental docs + `check_doc_drift`.
- **Phase 4:** `profiles.py` output profiles, `diagrams.py` Mermaid.
- **Phase 5:** `pyproject.toml` / `uvx` packaging, MCP registry, `action.yml` GitHub Action.
