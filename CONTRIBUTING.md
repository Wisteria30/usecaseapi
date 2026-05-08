# Contributing

Thank you for helping improve UseCaseAPI.

## Development setup

```bash
uv sync --extra dev
uv run pytest
uv run mypy
uv run ruff check .
uv run ruff format .
```

## Expectations

- Keep the public API small.
- Preserve the no-DI-container, no-transaction-manager scope.
- Keep all implementation fully typed and mypy-clean under strict mode.
- Add tests for behavior changes.
- Update docs when behavior or public API changes.

## Pull request checklist

- [ ] Tests pass.
- [ ] Mypy passes.
- [ ] Ruff passes.
- [ ] Docs are updated.
- [ ] New features do not add hidden serialization, hidden DI, or hidden transaction behavior.
