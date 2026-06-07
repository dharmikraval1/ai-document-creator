# Phase 2 — Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the AI Document Creator MCP server with SSRF guards, size caps, retry/backoff, structured logging, global concurrency + per-call timeouts, DNS-rebinding protection, a `/health` endpoint, BYOK mode, and PR-based push — making it production-ready for public deployment.

**Architecture:** A new `core/guards.py` module centralises all input-validation logic. A `core/retry.py` module provides a transparent `CompletionBackend` wrapper with tenacity-based backoff. A `core/logging_config.py` module adds structured JSON logging with per-request IDs via `contextvars`. `mcp_server_impl.py` is rewritten to wire all of the above together with a global semaphore, per-call `asyncio.wait_for` timeout, and BYOK override. `document_repo` gains three optional PR-push parameters backed by PyGithub.

**Tech Stack:** Python 3.11+, tenacity 8.x, PyGithub 2.x, existing MCP SDK 1.x (FastMCP with `custom_route`), LangGraph, pytest-asyncio.

> **Working directory:** All paths are relative to `ai-document-creator/`. Run every command from inside that directory. All commits land on `feature/phase2-hardening` branched from `feature/multi-provider-foundation`.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `core/guards.py` | SSRF URL validation, repo size cap, local path sandbox |
| Create | `core/retry.py` | Tenacity-based retry wrapper for `CompletionBackend` |
| Create | `core/logging_config.py` | JSON formatter, `REQUEST_ID_VAR` context var, `setup_logging()` |
| Create | `tests/test_guards.py` | Tests for all three guard functions |
| Create | `tests/test_retry.py` | Tests for retry behaviour |
| Create | `tests/test_logging_config.py` | Tests for JSON formatter and request-id injection |
| Create | `tests/test_pr_push.py` | Tests for `_push_docs_pr` and PR param handling |
| Modify | `core/config.py` | Add `pipeline_timeout_s: int = 300` to `DocConfig` |
| Modify | `core/sources.py` | `GitSource.prepare()` calls `validate_repo_url` + `validate_repo_size` |
| Modify | `core/backends.py` | `pick_backend()` wraps `ProviderBackend` with `with_retry()` |
| Modify | `mcp_server_impl.py` | Full rewrite: semaphore, timeout, BYOK, DNS allowlist, `/health`, logging, guards, PR push |
| Modify | `tests/test_backends.py` | Update one isinstance assertion broken by retry wrapping |
| Modify | `tests/test_sources.py` | Add two guard-integration tests for `GitSource` |
| Modify | `tests/test_mcp_tools.py` | Add semaphore, timeout, BYOK, health tests |
| Modify | `requirements.txt` | Add `tenacity`, `PyGithub`, `uvicorn` |
| Modify | `.env.example` | Document all new env vars |

---

## Task 0: Branch + dependencies

**Files:**
- Create branch: `feature/phase2-hardening`
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Create the working branch**

```bash
git checkout -b feature/phase2-hardening
```
Expected: `Switched to a new branch 'feature/phase2-hardening'`

- [ ] **Step 2: Add new dependencies to `requirements.txt`**

Append these three lines at the bottom of `requirements.txt`:
```
tenacity
PyGithub
uvicorn
```

- [ ] **Step 3: Install them**

```bash
.venv/Scripts/python.exe -m pip install tenacity PyGithub uvicorn -q
```
Expected: exits 0 with `Successfully installed ...` (no errors).

- [ ] **Step 4: Update `.env.example`**

Append to the end of `.env.example`:
```
# --- Phase 2: Hardening ---
MAX_CONCURRENT_PIPELINES=3
PIPELINE_TIMEOUT_S=300
MAX_REPO_MB=500
LOCAL_ROOT=
MCP_ALLOWED_HOSTS=localhost,127.0.0.1,localhost:*,127.0.0.1:*
LOG_FORMAT=
BYOK_ONLY=false
```

- [ ] **Step 5: Verify existing suite still green**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `43 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example
git commit -m "chore: add tenacity, PyGithub, uvicorn; document Phase 2 env vars"
```

---

## Task 1: `core/guards.py` — SSRF URL validation

**Files:**
- Create: `core/guards.py`
- Create: `tests/test_guards.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_guards.py
import socket
from unittest.mock import patch

import pytest

from core.guards import validate_repo_url


def _dns(ip: str):
    """Return a mock getaddrinfo result resolving to *ip*."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]


def test_valid_public_url_passes():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("140.82.121.4")):
        validate_repo_url("https://github.com/user/repo")


def test_http_scheme_rejected():
    with pytest.raises(ValueError, match="Only https://"):
        validate_repo_url("http://github.com/user/repo")


def test_git_scheme_rejected():
    with pytest.raises(ValueError, match="Only https://"):
        validate_repo_url("git://github.com/user/repo")


def test_file_scheme_rejected():
    with pytest.raises(ValueError, match="Only https://"):
        validate_repo_url("file:///etc/passwd")


def test_loopback_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("127.0.0.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://evil.example.com/repo")


def test_aws_metadata_ip_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("169.254.169.254")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://sneaky.example.com/repo")


def test_private_rfc1918_class_a_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("10.0.0.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://internal.corp/repo")


def test_private_rfc1918_class_c_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("192.168.1.1")):
        with pytest.raises(ValueError, match="private or reserved"):
            validate_repo_url("https://router.local/repo")


def test_google_metadata_hostname_rejected():
    with patch("core.guards.socket.getaddrinfo", return_value=_dns("169.254.169.254")):
        with pytest.raises(ValueError):
            validate_repo_url("https://metadata.google.internal/computeMetadata/v1/")


def test_dns_failure_rejected():
    with patch("core.guards.socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
        with pytest.raises(ValueError, match="Cannot resolve"):
            validate_repo_url("https://does-not-exist.invalid/repo")
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_guards.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'core.guards'`

- [ ] **Step 3: Implement `core/guards.py` (URL validation only)**

```python
# core/guards.py
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)

_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.internal"})


def validate_repo_url(url: str) -> None:
    """Raise ValueError if *url* fails SSRF safety checks.

    Blocks non-HTTPS schemes and any URL that resolves to private, loopback,
    link-local, carrier-NAT, or IPv6 unique-local address space.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"Only https:// repository URLs are accepted; got '{parsed.scheme}://'."
        )
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Repository URL has no hostname.")
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Hostname '{hostname}' is not permitted.")
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname '{hostname}': {exc}") from exc
    for _family, _type, _proto, _canon, sockaddr in addr_infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if any(ip in net for net in _PRIVATE_NETWORKS):
            raise ValueError(
                f"Repository URL resolves to a private or reserved IP address "
                f"({ip}), which is not permitted."
            )
```

- [ ] **Step 4: Run to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_guards.py -v
```
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add core/guards.py tests/test_guards.py
git commit -m "feat: add SSRF URL validation in core/guards.py"
```

---

## Task 2: `core/guards.py` — Repo size cap + local path sandbox

**Files:**
- Modify: `core/guards.py`
- Modify: `tests/test_guards.py`

- [ ] **Step 1: Append the failing tests to `tests/test_guards.py`**

```python
# ── append to tests/test_guards.py ──────────────────────────────────────────
import os
from core.guards import validate_local_path, validate_repo_size


def test_size_cap_passes_when_under_limit(tmp_path):
    (tmp_path / "small.txt").write_text("x" * 100, encoding="utf-8")
    validate_repo_size(str(tmp_path), max_mb=1)  # must not raise


def test_size_cap_raises_when_over_limit(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    with pytest.raises(ValueError, match="exceeds"):
        validate_repo_size(str(tmp_path), max_mb=1)


def test_local_path_allowed_when_local_root_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCAL_ROOT", raising=False)
    validate_local_path(str(tmp_path))  # must not raise


def test_local_path_allowed_within_root(monkeypatch, tmp_path):
    sub = tmp_path / "project"
    sub.mkdir()
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    validate_local_path(str(sub))  # must not raise


def test_local_path_blocked_outside_root(monkeypatch, tmp_path):
    outside = str(tmp_path.parent)
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="outside"):
        validate_local_path(outside)
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_guards.py -k "size or local_path" -v
```
Expected: FAIL — `ImportError: cannot import name 'validate_local_path'`

- [ ] **Step 3: Append two functions to `core/guards.py`**

```python
# ── append to core/guards.py ─────────────────────────────────────────────────

def validate_repo_size(repo_path: str, max_mb: int | None = None) -> None:
    """Raise ValueError if the total size of *repo_path* exceeds *max_mb* MB.

    *max_mb* defaults to the ``MAX_REPO_MB`` environment variable, or 500.
    """
    limit = max_mb if max_mb is not None else int(os.getenv("MAX_REPO_MB", "500"))
    limit_bytes = limit * 1024 * 1024
    total = 0
    for root, _dirs, files in os.walk(repo_path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    if total > limit_bytes:
        raise ValueError(
            f"Cloned repository size ({total // (1024 * 1024)} MB) "
            f"exceeds the {limit} MB limit."
        )


def validate_local_path(path: str) -> None:
    """Raise ValueError if *path* escapes the ``LOCAL_ROOT`` sandbox.

    Has no effect when ``LOCAL_ROOT`` is not set (local / stdio deployments).
    """
    local_root = os.getenv("LOCAL_ROOT", "").strip()
    if not local_root:
        return
    resolved = os.path.realpath(os.path.abspath(path))
    root = os.path.realpath(os.path.abspath(local_root))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError(
            f"Path '{path}' is outside the allowed LOCAL_ROOT '{local_root}'."
        )
```

- [ ] **Step 4: Run the full guards suite**

```bash
.venv/Scripts/python.exe -m pytest tests/test_guards.py -v
```
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
git add core/guards.py tests/test_guards.py
git commit -m "feat: add repo size cap and local path sandbox to guards"
```

---

## Task 3: Wire guards into `core/sources.py`

**Files:**
- Modify: `core/sources.py`
- Modify: `tests/test_sources.py`

- [ ] **Step 1: Append the failing tests to `tests/test_sources.py`**

```python
# ── append to tests/test_sources.py ──────────────────────────────────────────
import socket
from unittest.mock import patch

from core.sources import GitSource


def test_gitsource_prepare_rejects_http_url():
    src = GitSource("http://github.com/user/repo")
    with pytest.raises(ValueError, match="Only https://"):
        src.prepare()
    src.cleanup()


def test_gitsource_prepare_rejects_private_ip():
    with patch(
        "core.guards.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))],
    ):
        src = GitSource("https://internal.corp.example/repo")
        with pytest.raises(ValueError, match="private or reserved"):
            src.prepare()
        src.cleanup()
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_sources.py -k "rejects" -v
```
Expected: FAIL — the two new tests fail (no guard calls in `prepare` yet); all original source tests still pass.

- [ ] **Step 3: Update `GitSource.prepare()` in `core/sources.py`**

Replace the `prepare` method of `GitSource`:

```python
    def prepare(self) -> str:
        from git import Repo

        from .guards import validate_repo_size, validate_repo_url

        validate_repo_url(self.repo_url)
        logger.info("Cloning %s to %s", mask_token(self.repo_url), self.temp_dir)
        try:
            Repo.clone_from(self.repo_url, self.temp_dir)
            validate_repo_size(self.temp_dir)
            return self.temp_dir
        except Exception:
            self.cleanup()
            raise
```

- [ ] **Step 4: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `45 passed` (43 original + 2 new)

- [ ] **Step 5: Commit**

```bash
git add core/sources.py tests/test_sources.py
git commit -m "feat: validate URL and repo size inside GitSource.prepare()"
```

---

## Task 4: `core/config.py` — Add `pipeline_timeout_s`

**Files:**
- Modify: `core/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Append the failing test to `tests/test_config.py`**

```python
# ── append to tests/test_config.py ───────────────────────────────────────────
def test_pipeline_timeout_defaults_to_300():
    cfg = DocConfig()
    assert cfg.pipeline_timeout_s == 300


def test_resolve_config_reads_pipeline_timeout_from_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_TIMEOUT_S", "120")
    cfg = resolve_config()
    assert cfg.pipeline_timeout_s == 120
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py -k "timeout" -v
```
Expected: FAIL — `AttributeError: 'DocConfig' object has no attribute 'pipeline_timeout_s'`

- [ ] **Step 3: Update `core/config.py`**

Add `pipeline_timeout_s: int = 300` to `DocConfig` and teach `resolve_config` to read the env override. Replace the entire file:

```python
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
```

- [ ] **Step 4: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `47 passed`

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat: add pipeline_timeout_s to DocConfig with env override"
```

---

## Task 5: `core/retry.py` — Retry wrapper + wire into `pick_backend`

**Files:**
- Create: `core/retry.py`
- Create: `tests/test_retry.py`
- Modify: `core/backends.py`
- Modify: `tests/test_backends.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_retry.py
import pytest
from tenacity import wait_none

from core.backends import BackendError, CompletionBackend, FakeBackend
from core.retry import with_retry


class _FailNTimes(CompletionBackend):
    """Fails the first *n* calls, then returns *then_return*."""

    def __init__(self, n: int, then_return: str = "OK"):
        self.calls = 0
        self._n = n
        self._then = then_return

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        if self.calls <= self._n:
            raise RuntimeError(f"transient error #{self.calls}")
        return self._then


async def test_retries_and_succeeds_after_transient_failures():
    inner = _FailNTimes(n=2)
    backend = with_retry(inner, max_attempts=3, _wait=wait_none())
    result = await backend.complete("hello")
    assert result == "OK"
    assert inner.calls == 3


async def test_raises_after_exhausting_attempts():
    inner = _FailNTimes(n=99)
    backend = with_retry(inner, max_attempts=3, _wait=wait_none())
    with pytest.raises(RuntimeError, match="transient error"):
        await backend.complete("hello")
    assert inner.calls == 3


async def test_does_not_retry_backend_error():
    class _BadConfig(CompletionBackend):
        async def complete(self, prompt: str) -> str:
            raise BackendError("config error")

    backend = with_retry(_BadConfig(), max_attempts=3, _wait=wait_none())
    with pytest.raises(BackendError):
        await backend.complete("hello")


async def test_does_not_retry_value_error():
    class _BadInput(CompletionBackend):
        async def complete(self, prompt: str) -> str:
            raise ValueError("bad input")

    backend = with_retry(_BadInput(), max_attempts=3, _wait=wait_none())
    with pytest.raises(ValueError):
        await backend.complete("hello")


async def test_wrapped_backend_is_a_completion_backend():
    assert isinstance(with_retry(FakeBackend(), _wait=wait_none()), CompletionBackend)
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_retry.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'core.retry'`

- [ ] **Step 3: Create `core/retry.py`**

```python
# core/retry.py
from __future__ import annotations

import logging

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .backends import BackendError, CompletionBackend

logger = logging.getLogger(__name__)


def with_retry(
    backend: CompletionBackend,
    max_attempts: int = 3,
    _wait=None,
) -> CompletionBackend:
    """Return a backend whose ``complete()`` retries on transient failures.

    *_wait* is a tenacity wait strategy; it defaults to exponential backoff
    and exists solely so tests can pass ``wait_none()`` for instant retries.
    """
    return _RetryBackend(backend, max_attempts=max_attempts, _wait=_wait)


class _RetryBackend(CompletionBackend):
    def __init__(self, inner: CompletionBackend, max_attempts: int, _wait=None) -> None:
        wait_strategy = (
            _wait
            if _wait is not None
            else wait_exponential(multiplier=1, min=1, max=8)
        )

        @retry(
            retry=retry_if_not_exception_type((BackendError, ValueError, TypeError)),
            stop=stop_after_attempt(max_attempts),
            wait=wait_strategy,
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _run(prompt: str) -> str:
            return await inner.complete(prompt)

        self._run = _run

    async def complete(self, prompt: str) -> str:
        return await self._run(prompt)
```

- [ ] **Step 4: Run retry tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_retry.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Wire retry into `pick_backend` in `core/backends.py`**

Replace only the `pick_backend` function at the bottom of `core/backends.py`:

```python
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
```

- [ ] **Step 6: Update the broken isinstance assertion in `tests/test_backends.py`**

Find and replace this test (it checks the concrete type, which changed because `pick_backend` now wraps with retry):

Old:
```python
async def test_pick_backend_prefers_provider_when_key_present(monkeypatch):
    import core.backends as backends
    monkeypatch.setattr(backends, "init_chat_model", lambda *a, **k: _FakeModel())
    from core.config import DocConfig
    backend = backends.pick_backend(DocConfig(provider="openai"), ctx=_FakeCtx())
    assert isinstance(backend, backends.ProviderBackend)
```

New (tests the contract, not the wrapper type):
```python
async def test_pick_backend_prefers_provider_when_key_present(monkeypatch):
    import core.backends as backends
    monkeypatch.setattr(backends, "init_chat_model", lambda *a, **k: _FakeModel())
    from core.config import DocConfig
    backend = backends.pick_backend(DocConfig(provider="openai"), ctx=_FakeCtx())
    assert isinstance(backend, backends.CompletionBackend)
    assert not isinstance(backend, backends.SamplingBackend)
```

- [ ] **Step 7: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `52 passed`

- [ ] **Step 8: Commit**

```bash
git add core/retry.py tests/test_retry.py core/backends.py tests/test_backends.py
git commit -m "feat: add retry wrapper and wire into pick_backend"
```

---

## Task 6: `core/logging_config.py` — Structured JSON logging

**Files:**
- Create: `core/logging_config.py`
- Create: `tests/test_logging_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_logging_config.py
import json
import logging

from core.logging_config import REQUEST_ID_VAR, setup_logging


def test_plain_format_does_not_crash():
    setup_logging(json_mode=False)
    logging.getLogger("test").info("plain log")


def test_json_format_produces_valid_json(capsys):
    setup_logging(json_mode=True)
    REQUEST_ID_VAR.set("abc123")
    logging.getLogger("test_json").warning("hello world")
    captured = capsys.readouterr()
    # Find the JSON line in captured stderr
    for line in captured.err.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("message") == "hello world":
            assert data["level"] == "WARNING"
            assert data["logger"] == "test_json"
            assert data["request_id"] == "abc123"
            assert "timestamp" in data
            return
    raise AssertionError("No matching JSON log line found in output")


def test_request_id_defaults_to_dash(capsys):
    setup_logging(json_mode=True)
    REQUEST_ID_VAR.set("-")
    logging.getLogger("test_default").info("no id")
    captured = capsys.readouterr()
    for line in captured.err.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("message") == "no id":
            assert data["request_id"] == "-"
            return
    raise AssertionError("No matching JSON log line found")
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_logging_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'core.logging_config'`

- [ ] **Step 3: Create `core/logging_config.py`**

```python
# core/logging_config.py
from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone

REQUEST_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "request_id": getattr(record, "request_id", "-"),
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID_VAR.get("-")
        return True


def setup_logging(json_mode: bool = False) -> None:
    """Configure the root logger. Call once at process startup."""
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if json_mode:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
```

- [ ] **Step 4: Run logging tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_logging_config.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `55 passed`

- [ ] **Step 6: Commit**

```bash
git add core/logging_config.py tests/test_logging_config.py
git commit -m "feat: add structured JSON logging with per-request context var"
```

---

## Task 7: Rewrite `mcp_server_impl.py`

This task replaces `mcp_server_impl.py` in full. It wires together: global semaphore, per-call timeout, BYOK override, DNS-rebinding protection, `/health` endpoint, structured logging, and guard calls in both tools.

**Files:**
- Modify: `mcp_server_impl.py` (full replace)
- Modify: `tests/test_mcp_tools.py`

- [ ] **Step 1: Append the failing tests to `tests/test_mcp_tools.py`**

```python
# ── append to tests/test_mcp_tools.py ────────────────────────────────────────
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


async def test_health_endpoint_returns_ok():
    from mcp_server_impl import health

    class _Req:
        pass

    response = await health(_Req())
    data = json.loads(response.body)
    assert data == {"status": "ok", "version": "2.0.0"}


async def test_document_local_project_times_out(monkeypatch, tmp_path):
    import mcp_server_impl as server
    from core.config import DocConfig

    async def _slow(*_a, **_kw):
        await asyncio.sleep(999)
        return "never"

    monkeypatch.setattr(server, "_run_pipeline", _slow)
    monkeypatch.setattr(server, "validate_local_path", lambda _p: None)
    monkeypatch.setattr(
        server, "resolve_config", lambda **_kw: DocConfig(pipeline_timeout_s=1)
    )

    result = await server.document_local_project(path=str(tmp_path), ctx=None)
    assert "timed out" in result


async def test_document_local_project_rejects_bad_path(monkeypatch):
    import mcp_server_impl as server

    def _raise(_p):
        raise ValueError("outside LOCAL_ROOT")

    monkeypatch.setattr(server, "validate_local_path", _raise)
    result = await server.document_local_project(path="/etc", ctx=None)
    assert "Error:" in result
    assert "outside" in result


async def test_document_repo_rejects_http_url():
    import mcp_server_impl as server

    result = await server.document_repo(repo_url="http://github.com/user/repo", ctx=None)
    assert "Error:" in result
    assert "https" in result
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -k "health or timed_out or rejects" -v
```
Expected: FAIL — the new tests fail (old `mcp_server_impl.py` has none of these)

- [ ] **Step 3: Replace `mcp_server_impl.py` entirely**

```python
# mcp_server_impl.py
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from github import Github, GithubException

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from core.config import DocConfig, resolve_config
from core.backends import pick_backend
from core.guards import validate_local_path, validate_repo_url
from core.logging_config import REQUEST_ID_VAR, setup_logging
from core.sources import GitSource, LocalSource
from core.file_traverser import FileTraverser
from core.graph import app as workflow_app
from core.doc_writer import DocumentationWriter

setup_logging(json_mode=os.getenv("LOG_FORMAT", "").lower() == "json")
logger = logging.getLogger(__name__)

__version__ = "2.0.0"

_BYOK_ONLY: bool = os.getenv("BYOK_ONLY", "").lower() == "true"
_pipeline_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_PIPELINES", "3")))


def _parse_allowed_hosts() -> list[str]:
    raw = os.getenv(
        "MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,localhost:*,127.0.0.1:*"
    )
    return [h.strip() for h in raw.split(",") if h.strip()]


mcp = FastMCP(
    "AI Document Creator",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_parse_allowed_hosts(),
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


async def _run_pipeline(source, output_dir: str, config: DocConfig, ctx) -> str:
    try:
        repo_path = source.prepare()
        files = list(
            FileTraverser(repo_path, max_file_size_kb=config.max_file_size_kb).traverse()
        )
        if not files:
            return "No files found to document."

        effective_config = DocConfig() if _BYOK_ONLY else config
        backend = pick_backend(effective_config, ctx=ctx)

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
        logger.error("Pipeline error: %s", exc)
        return f"Error occurred: {exc}"
    finally:
        source.cleanup()


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _parse_github_slug(repo_url: str) -> tuple[str, str]:
    match = re.search(
        r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url
    )
    if not match:
        raise ValueError(f"Cannot parse GitHub owner/repo from URL: {repo_url}")
    return match.group(1), match.group(2)


async def _push_docs_pr(
    repo_url: str,
    docs_dir: str,
    branch: str,
    title: str,
    github_token: str,
) -> str:
    """Commit generated docs to a branch on GitHub and open a PR. Returns PR URL."""
    loop = asyncio.get_running_loop()

    def _sync() -> str:
        owner, repo_name = _parse_github_slug(repo_url)
        gh = Github(github_token)
        gh_repo = gh.get_repo(f"{owner}/{repo_name}")
        default_branch = gh_repo.default_branch
        base_sha = gh_repo.get_branch(default_branch).commit.sha

        try:
            gh_repo.create_git_ref(f"refs/heads/{branch}", base_sha)
        except GithubException as exc:
            if exc.status != 422:  # 422 = branch already exists
                raise

        commit_message = "docs: add AI-generated documentation"
        for fname in os.listdir(docs_dir):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(docs_dir, fname), "r", encoding="utf-8") as fh:
                content = fh.read()
            target = f"docs/{fname}"
            try:
                existing = gh_repo.get_contents(target, ref=branch)
                gh_repo.update_file(
                    target, commit_message, content, existing.sha, branch=branch
                )
            except GithubException as exc:
                if exc.status == 404:
                    gh_repo.create_file(target, commit_message, content, branch=branch)
                else:
                    raise

        pr = gh_repo.create_pull(
            title=title,
            body=(
                "Auto-generated documentation by "
                "[AI Document Creator]"
                "(https://github.com/dharmikraval1/ai-document-creator)."
            ),
            head=branch,
            base=default_branch,
        )
        return pr.html_url

    try:
        return await loop.run_in_executor(None, _sync)
    except Exception as exc:
        logger.error("PR push failed: %s", exc)
        return f"⚠️ PR push failed: {exc}"


@mcp.tool()
async def document_local_project(
    path: str = ".",
    output_dir: str = "docs",
    provider: str | None = None,
    model: str | None = None,
    ctx: Context = None,
) -> str:
    """Generate documentation for a project folder on the local machine.

    Args:
        path: Path to the local project directory.
        output_dir: Where to write the generated markdown files.
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama). Auto-detected
            from env if omitted; falls back to host sampling when no key is configured.
        model: Model name override (uses provider default when omitted).
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_local_project started path=%s", path)

    try:
        validate_local_path(path)
    except ValueError as exc:
        return f"Error: {exc}"

    config = resolve_config(provider=provider, model=model)
    async with _pipeline_semaphore:
        try:
            return await asyncio.wait_for(
                _run_pipeline(LocalSource(path), output_dir, config, ctx),
                timeout=config.pipeline_timeout_s,
            )
        except asyncio.TimeoutError:
            return (
                f"Error: pipeline timed out after {config.pipeline_timeout_s}s. "
                "The project may be too large or the LLM provider is unresponsive."
            )


@mcp.tool()
async def document_repo(
    repo_url: str,
    output_dir: str = "docs",
    github_token: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    push_as_pr: bool = False,
    pr_branch: str | None = None,
    pr_title: str | None = None,
    ctx: Context = None,
) -> str:
    """Generate documentation for a GitHub repository (clones it first).

    Args:
        repo_url: HTTPS URL of the repository to document.
        output_dir: Where to write the generated markdown files.
        github_token: Token for private repos (falls back to GITHUB_TOKEN env var).
        provider: LLM provider (anthropic/openai/azure/bedrock/ollama).
        model: Model name override.
        push_as_pr: If True, commit the generated docs to a branch and open a PR.
        pr_branch: Branch name (default: docs/ai-generated-{timestamp}).
        pr_title: PR title (default: "docs: AI-generated documentation").
    """
    REQUEST_ID_VAR.set(uuid.uuid4().hex[:8])
    logger.info("document_repo started url=%s push_as_pr=%s", repo_url, push_as_pr)

    try:
        validate_repo_url(repo_url)
    except ValueError as exc:
        return f"Error: {exc}"

    config = resolve_config(provider=provider, model=model)
    async with _pipeline_semaphore:
        try:
            report = await asyncio.wait_for(
                _run_pipeline(
                    GitSource(repo_url, github_token=github_token),
                    output_dir,
                    config,
                    ctx,
                ),
                timeout=config.pipeline_timeout_s,
            )
        except asyncio.TimeoutError:
            return (
                f"Error: pipeline timed out after {config.pipeline_timeout_s}s. "
                "The repository may be too large or the LLM provider is unresponsive."
            )

    if push_as_pr and not report.startswith("Error"):
        token = github_token or os.getenv("GITHUB_TOKEN")
        if not token:
            report += (
                "\n\n⚠️ `push_as_pr=True` was requested but no GitHub token is "
                "available — skipping PR creation."
            )
        else:
            pr_url = await _push_docs_pr(
                repo_url=repo_url,
                docs_dir=os.path.abspath(output_dir),
                branch=pr_branch or f"docs/ai-generated-{_timestamp()}",
                title=pr_title or "docs: AI-generated documentation",
                github_token=token,
            )
            report += f"\n\n## Pull Request\n\n{pr_url}"

    return report


if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        logger.info("Starting MCP server in SSE mode on port %s", port_env)
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port_env)
        mcp.run(transport="sse")
    else:
        logger.info("Starting MCP server in stdio mode")
        mcp.run()
```

- [ ] **Step 4: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `59 passed`

- [ ] **Step 5: Commit**

```bash
git add mcp_server_impl.py tests/test_mcp_tools.py
git commit -m "feat: harden MCP server — semaphore, timeout, BYOK, DNS guard, health, JSON logging"
```

---

## Task 8: PR-based push tests

The `_push_docs_pr` function and the PR parameter flow are already in `mcp_server_impl.py` from Task 7. This task adds the test coverage.

**Files:**
- Create: `tests/test_pr_push.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_pr_push.py
import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest


def _make_gh_repo(default_branch="main", existing_files=None):
    """Return a minimal mock of a PyGithub Repository object."""
    branch_mock = MagicMock()
    branch_mock.commit.sha = "abc123"

    repo = MagicMock()
    repo.default_branch = default_branch
    repo.get_branch.return_value = branch_mock
    repo.create_git_ref.return_value = MagicMock()

    pr_mock = MagicMock()
    pr_mock.html_url = "https://github.com/user/repo/pull/1"
    repo.create_pull.return_value = pr_mock

    if existing_files:
        def _get_contents(path, ref=None):
            if path in existing_files:
                m = MagicMock()
                m.sha = "fileSHA"
                return m
            from github import GithubException
            raise GithubException(404, "not found")
        repo.get_contents.side_effect = _get_contents
    else:
        from github import GithubException
        repo.get_contents.side_effect = GithubException(404, "not found")

    return repo


def test_parse_github_slug_standard_url():
    from mcp_server_impl import _parse_github_slug
    assert _parse_github_slug("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_github_slug_with_dot_git():
    from mcp_server_impl import _parse_github_slug
    assert _parse_github_slug("https://github.com/owner/repo.git") == ("owner", "repo")


def test_parse_github_slug_invalid_url():
    from mcp_server_impl import _parse_github_slug
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_github_slug("https://gitlab.com/owner/repo")


async def test_push_docs_pr_creates_files_and_pr(tmp_path):
    (tmp_path / "README.md").write_text("# Hello", encoding="utf-8")
    (tmp_path / "main.py.md").write_text("# main", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("not md", encoding="utf-8")

    gh_repo = _make_gh_repo()

    mock_gh = MagicMock()
    mock_gh.return_value.get_repo.return_value = gh_repo

    with patch("mcp_server_impl.Github", mock_gh):
        from mcp_server_impl import _push_docs_pr
        result = await _push_docs_pr(
            repo_url="https://github.com/user/repo",
            docs_dir=str(tmp_path),
            branch="docs/test-branch",
            title="docs: test",
            github_token="fake-token",
        )

    assert result == "https://github.com/user/repo/pull/1"
    # Only .md files committed — the .txt file must be ignored
    assert gh_repo.create_file.call_count == 2
    gh_repo.create_pull.assert_called_once_with(
        title="docs: test",
        body="Auto-generated documentation by [AI Document Creator](https://github.com/dharmikraval1/ai-document-creator).",
        head="docs/test-branch",
        base="main",
    )


async def test_push_docs_pr_updates_existing_files(tmp_path):
    (tmp_path / "README.md").write_text("# Updated", encoding="utf-8")

    gh_repo = _make_gh_repo(existing_files={"docs/README.md"})
    mock_gh = MagicMock()
    mock_gh.return_value.get_repo.return_value = gh_repo

    with patch("mcp_server_impl.Github", mock_gh):
        from mcp_server_impl import _push_docs_pr
        await _push_docs_pr(
            repo_url="https://github.com/user/repo",
            docs_dir=str(tmp_path),
            branch="docs/test-branch",
            title="docs: update",
            github_token="fake-token",
        )

    gh_repo.update_file.assert_called_once()
    gh_repo.create_file.assert_not_called()


async def test_document_repo_skips_pr_when_no_token(monkeypatch):
    import mcp_server_impl as server

    async def _fake_pipeline(*_a, **_kw):
        return "# Documentation Generation Report\n\n- **Files Processed**: 1\n"

    monkeypatch.setattr(server, "validate_repo_url", lambda _u: None)
    monkeypatch.setattr(server, "_run_pipeline", _fake_pipeline)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    result = await server.document_repo(
        repo_url="https://github.com/user/repo",
        output_dir="/tmp/docs",
        github_token=None,
        push_as_pr=True,
        ctx=None,
    )

    assert "skipping PR creation" in result
```

- [ ] **Step 2: Run to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_pr_push.py -v
```
Expected: `6 passed`

Note: `test_document_repo_skips_pr_when_no_token` patches `validate_repo_url` and `pick_backend` to avoid network calls. If it fails with an import error on `github`, install: `.venv/Scripts/python.exe -m pip install PyGithub -q`.

- [ ] **Step 3: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
Expected: `≥ 65 passed, 0 failed`

- [ ] **Step 4: Commit**

```bash
git add tests/test_pr_push.py
git commit -m "test: cover PR push — creation, update, token-missing graceful skip"
```

---

## Task 9: Final verification + PHASE2_STATUS.md + push

**Files:**
- Create: `planning/PHASE2_STATUS.md`
- Modify: `planning/PHASE1_STATUS.md` (update active branch line)

- [ ] **Step 1: Run the complete test suite**

```bash
.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -20
```
Expected: all tests pass, 0 failures. Count should be ≥ 65.

- [ ] **Step 2: Run type checking**

```bash
.venv/Scripts/python.exe -m mypy core/ mcp_server_impl.py --ignore-missing-imports 2>&1 | tail -10
```
Expected: `Success: no issues found` or only ignorable missing-stub warnings. Fix any real type errors before continuing.

- [ ] **Step 3: Run linting**

```bash
.venv/Scripts/python.exe -m flake8 core/ mcp_server_impl.py --max-line-length=100 --extend-ignore=E203,W503
```
Expected: exits 0 with no output.

- [ ] **Step 4: Smoke-test the CLI (no provider)**

```bash
.venv/Scripts/python.exe main.py --path . --output /tmp/smoke_docs
```
Expected: clear `BackendError` message about setting a provider key — confirms `pick_backend` (and retry wrapper) still guard correctly without a key.

- [ ] **Step 5: Write `planning/PHASE2_STATUS.md`**

```markdown
# Phase 2 Status — Hardening

**Last updated:** 2026-06-06  
**Branch:** `feature/phase2-hardening`  
**Test status:** ✅ ≥ 65 passing

## What was built

- `core/guards.py` — SSRF URL validation (RFC 1918 + metadata blocklist), repo size cap,
  local path sandbox (`LOCAL_ROOT`).
- `core/retry.py` — `with_retry()` tenacity wrapper; exponential backoff (1 s → 2 s → 4 s);
  does not retry `BackendError` / `ValueError`.
- `core/logging_config.py` — `setup_logging(json_mode)`, `_JsonFormatter`, `REQUEST_ID_VAR`
  context var injected into every log record.
- `core/config.py` — `DocConfig.pipeline_timeout_s` (default 300 s, env `PIPELINE_TIMEOUT_S`).
- `core/sources.py` — `GitSource.prepare()` now calls `validate_repo_url` + `validate_repo_size`
  before any network I/O.
- `core/backends.py` — `pick_backend()` wraps `ProviderBackend` with `with_retry()`.
- `mcp_server_impl.py` — full rewrite:
  - Module-level `asyncio.Semaphore(MAX_CONCURRENT_PIPELINES)` caps parallel pipelines.
  - `asyncio.wait_for(pipeline, timeout=config.pipeline_timeout_s)` per tool call.
  - `BYOK_ONLY=true` forces sampling backend regardless of operator env keys.
  - DNS-rebinding protection re-enabled; `MCP_ALLOWED_HOSTS` env for allowlist.
  - `@mcp.custom_route("/health")` returns `{"status":"ok","version":"2.0.0"}`.
  - `setup_logging(json_mode)` called once at startup.
  - `REQUEST_ID_VAR` set at the top of each tool call.
  - `document_repo` gains `push_as_pr`, `pr_branch`, `pr_title` parameters.
  - `_push_docs_pr` commits `.md` files to a branch via PyGithub Contents API and opens a PR.

## How to resume (fresh device)

```bash
git clone https://github.com/dharmikraval1/ai-document-creator.git
cd ai-document-creator
git checkout feature/phase2-hardening
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest -q  # expect ≥ 65 passed
```

## Remaining phases

- **Phase 3 — Incremental + drift:** `core/cache.py` content-hash manifest; only regenerate
  changed files; `check_doc_drift` MCP tool.
- **Phase 4 — Profiles + diagrams:** `core/profiles.py` (readme / api-reference / onboarding);
  `core/diagrams.py` (Mermaid architecture + dependency graphs).
- **Phase 5 — Packaging + GitHub Action:** `pyproject.toml` / `uvx` entry-point; MCP registry
  listing; `action.yml` that opens a PR with generated docs on every push.
```

- [ ] **Step 6: Commit everything and push**

```bash
git add planning/PHASE2_STATUS.md
git commit -m "docs: add Phase 2 status handoff"
git push -u origin feature/phase2-hardening
```

---

## Definition of Done

- [ ] `pytest -q` reports ≥ 65 passing, 0 failing
- [ ] `mypy core/ mcp_server_impl.py --ignore-missing-imports` clean
- [ ] `flake8 core/ mcp_server_impl.py --max-line-length=100` clean
- [ ] `document_repo("http://...", ...)` returns `Error: Only https://`
- [ ] `document_local_project` with `LOCAL_ROOT` set blocks paths outside it
- [ ] `/health` handler returns `{"status":"ok","version":"2.0.0"}`
- [ ] `LOG_FORMAT=json` produces one valid JSON object per log line
- [ ] `BYOK_ONLY=true` causes `pick_backend` to receive a no-provider config
- [ ] `push_as_pr=True` with no token returns the warning string, not an exception
- [ ] `feature/phase2-hardening` pushed to `origin` and ready for PR → `main`
