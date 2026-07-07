# Contributing

Thanks for your interest! This project welcomes issues and pull requests.

## Development setup

```bash
git clone https://github.com/dharmikraval1/ai-document-creator
cd ai-document-creator
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before opening a PR

All three must pass (CI enforces them on Python 3.11 and 3.12):

```bash
pytest -q
flake8
mypy ai_doc_creator --ignore-missing-imports
```

- Add tests for any behavior change — the suite runs fully offline
  (`FakeBackend` stands in for real LLMs; no keys needed).
- Keep changes focused; one topic per PR.
- Design specs and phase plans live in [planning/](planning/) — larger changes
  should start with a short design note there.

## Project layout

```
ai_doc_creator/          the installable package
├── cli.py               CLI entry point (ai-doc-creator)
├── server.py            MCP server (ai-doc-creator-mcp): tools, transports, BYOK
└── core/                pipeline: config, backends, sources, guards, graph,
                         cache, ratelimit, doc_writer, file_traverser
tests/                   pytest suite (offline, no API keys required)
```
