# Release Process

UseCaseAPI uses uv for packaging and GitHub Actions for publishing to PyPI.

## Local release validation

Run the same checks the release workflow runs before creating a tag:

```bash
uv sync --extra dev
uv run coverage run -m pytest
uv run coverage report -m
uv run mypy
uv run ruff check .
uv build
uv run twine check dist/*
uv run --isolated --no-project --with dist/*.whl scripts/verify_distribution.py
uv run --isolated --no-project --with dist/*.tar.gz scripts/verify_distribution.py
```

The distribution verification script imports the installed package, calls a real usecase, and checks that the `usecaseapi` CLI can create a versioned scaffold.

## Versioning

Version numbers follow semantic versioning. Contract-runtime behavior changes require careful release notes because downstream applications may rely on strict guardrail behavior.

Update both of these before tagging a release:

- `pyproject.toml` `[project].version`
- `src/usecaseapi/__init__.py` `__version__`

## Publishing

Publishing is handled by `.github/workflows/release.yml` when a tag matching `v*` is pushed.

The workflow expects PyPI Trusted Publishing:

- GitHub environment: `pypi`
- Repository owner: `Wisteria30`
- Repository name: `usecaseapi`
- Workflow filename: `release.yml`

The workflow uses GitHub OIDC and `uv publish`; no PyPI API token should be stored in repository secrets.

## Human release checklist

1. Confirm the package name `usecaseapi` is still available on PyPI and TestPyPI.
2. Create or log in to the PyPI account that will own the project.
3. Configure PyPI Trusted Publishing for this repository and workflow.
4. Create the `pypi` GitHub environment and require approval if desired.
5. Review the generated package metadata and README rendering locally.
6. Update the release version and changelog or GitHub release notes.
7. Create and push an annotated tag, for example `v1.0.0`.
8. Confirm the GitHub Actions release workflow completed and the PyPI project page is correct.
