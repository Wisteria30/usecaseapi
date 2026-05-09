# Agent Guidelines

This file defines how AI agents and human contributors should work in this repository. UseCaseAPI is an open source Python library, so guidance must be reproducible by public contributors. Do not assume private tools, local absolute paths, personal shell configuration, or maintainer-only services.

Prefer YAGNI, KISS, and DRY. Choose simple, readable, testable designs over pathological correctness. Unapproved fallback behavior is a bug. Do not silently invent behavior that has not been specified.

## Language And Encoding

- Repository files, public documentation, PR descriptions, code comments, and user-facing package metadata should be written in English by default.
- If a maintainer or user explicitly asks in another language, respond in that language while keeping repository artifacts suitable for OSS readers.
- Use UTF-8 for all text files.
- Code, public API names, error messages, CLI output, and PyPI metadata should be clear English.
- Do not treat vague manual inspection as completion evidence. Report the exact commands run and their results.

## Repository Purpose

UseCaseAPI is a Python library for treating same-process application use cases as versioned contracts.

This repository is responsible for:

- defining use case contracts from `Protocol`, Pydantic v2 models, and domain exceptions;
- binding contract tokens to implementation factories explicitly;
- exposing a use case dependency graph, snapshots, diffs, Markdown docs, Mermaid graph output, and CLI scaffolding;
- avoiding HTTP, RPC, dependency injection containers, and transaction managers as runtime requirements;
- maintaining publishable Python package quality for PyPI.

## Project Structure

- `src/usecaseapi/`: library source, including public API, runtime, contracts, snapshots, docs, and CLI scaffolding.
- `tests/`: pytest coverage for unit-level and package-level behavior.
- `examples/basic/`: minimal example project for contributors and users.
- `docs/`: design notes, usage guides, publishing notes, and API reference.
- `scripts/`: small CI and release verification helpers.
- `.github/workflows/`: CI and release workflows.

Do not commit generated files or local caches. This includes `.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `*.pyc`, `.coverage`, `coverage.json`, `htmlcov/`, `build/`, `dist/`, and `*.egg-info/`.

## Architecture Principles

- Public contracts should be expressed through `UseCaseRef`, `Contract`, `UseCase`, `Model`, and `UseCaseError`.
- Runtime behavior should remain same-process direct calls. Do not add serialization layers unless the feature explicitly requires them.
- Pass dependencies explicitly. Do not add global state, hidden service locators, or direct environment-variable reads to production code.
- Preserve the existing small-module structure. Avoid large helper modules, catch-all utility modules, and broad abstractions.
- Add abstractions only when they remove real duplication or reduce meaningful complexity.
- When changing the API surface, check `src/usecaseapi/__init__.py`, docs, and tests together.
- Keep `py.typed` valid so downstream users can type-check this package with mypy.

## Python Rules

- Support Python `>=3.12,<3.15`, matching the CI matrix.
- Use `uv` for dependency management. Do not add `requirements.txt`, use `pip install` in project instructions, or vendor dependencies manually.
- Use Pydantic v2.
- Use async use case calls as the default. Add sync code only when the responsibility is CPU-bound or does not involve I/O.
- Do not omit type annotations. Treat strict mypy as the baseline.
- Use `Any` only at dynamic API or metaclass-like boundaries where it is genuinely necessary. Do not use it as a convenience escape hatch.
- Comments should explain why a decision exists, not narrate what the code already says.
- Do not implement unapproved fallback behavior. Unsupported or unimplemented behavior should fail explicitly.

## Style And Naming

- Python style is 4-space indentation, double quotes, and line length 100.
- Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants.
- Public API names should be specific enough that users can infer their responsibility without reading internals.
- Keep domain contract exceptions and runtime validation exceptions clearly separated.
- Ruff configuration is the source of truth for import order, lint, and formatting rules. Do not weaken tests or configuration to avoid code fixes.

## Testing Guidelines

- Cover the main success path, important failure paths, and boundary conditions for every behavior change.
- Expand existing tests when a change affects contracts, binding, snapshots, diffs, docs, scaffolding, CLI behavior, or package installation.
- Do not remove tests, weaken assertions, or exclude code from checks to make CI pass.
- Keep external-service or network-dependent checks separate from ordinary unit tests and mark them explicitly.
- Test doubles belong in tests only. Do not put mock, stub, fake, or placeholder implementations in production code.
- Prefer tests whose Given / When / Then structure is easy to read. Move complex setup into fixtures.

## Development Commands

Run commands from the repository root.

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run coverage run -m pytest
uv run coverage report -m
uv build
uv run twine check dist/*
```

When validating package installation, check both wheel and source distribution artifacts after building.

```bash
uv run --isolated --no-project --with dist/*.whl scripts/verify_distribution.py
uv run --isolated --no-project --with dist/*.tar.gz scripts/verify_distribution.py
```

For CI-equivalent validation, run pytest and Ruff on Python 3.12, 3.13, and 3.14. Keep CI configured to report coverage before/after automatically on pull requests.

## Documentation Rules

- When changing public APIs, CLI behavior, scaffolding, snapshots, diffs, or package metadata, check whether README and docs need updates.
- Documentation must be reproducible by OSS contributors. Do not rely on personal shell setup, local absolute paths, private services, or maintainer-only credentials.
- Document source definitions and regeneration commands instead of committing generated output without context.
- If release or PyPI publishing behavior changes, review `RELEASE.md` and `docs/pypi-publishing.md`.

## Security And Configuration

- Never commit secrets, tokens, personal account values, or `.env` files.
- Keep CI permissions minimal. Grant write permissions only to jobs that need them and make the reason clear.
- Keep `uv.lock` and `pyproject.toml` consistent when updating dependencies.
- `tool.uv.exclude-newer` reduces supply-chain risk. If you change it, explain the reason in the PR.

## Git And PR Workflow

- Use branch names that describe the work, such as `feat/scaffold-docs`, `fix/snapshot-diff`, or `chore/ruff-config`.
- Prefer Conventional Commits, such as `feat: add scaffold option` or `fix: reject invalid contract errors`.
- PRs should include purpose, rationale, major changes, impact, validation commands, and related issues.
- Keep refactors separate from behavior changes when practical.
- Keep PRs small enough for reviewers to understand the diff and evidence.

## AI Governance Rules

- Before proposing a plan, state the ideal target, current truth, gap, scope, and completion evidence.
- Before claiming completion, verify the latest commands and outputs. Do not rely only on earlier runs.
- For long-running or high-risk changes, compare the implementation claim against the actual diff and verification results.
- Do not put mock, stub, fake, placeholder, or unapproved fallback behavior in production code.
- Do not update status or docs to imply completion before implementation and verification are complete.
- If evidence is incomplete, say the work is partial and list the remaining checks or decisions.
