# Release Process

UseCaseAPI uses uv for packaging.

## Build locally

```bash
uv sync --extra dev
uv run pytest
uv run mypy
uv run ruff check .
uv build
```

## Publish

Publishing is handled by the GitHub Actions release workflow using trusted publishing when configured.

Version numbers follow semantic versioning. Contract-runtime behavior changes require careful release notes because downstream applications may rely on strict guardrail behavior.
