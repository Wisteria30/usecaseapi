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

`pyproject.toml` `[project].version` is the release source of truth.

The `src/usecaseapi/__init__.py` module intentionally does not define
`__version__`; installed package metadata is the source for published versions.

## Publishing

Publishing is handled by `.github/workflows/release.yml`.

On `main`, the workflow detects changes to `pyproject.toml` `[project].version`,
validates the package, creates the annotated `v{version}` tag, and publishes to
PyPI. Pushing a matching `v*` tag or running the workflow manually also publishes
the current package version.

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
6. Update `pyproject.toml` `[project].version` and changelog or GitHub release notes.
7. Merge the version bump to `main`; GitHub Actions creates the annotated tag and publishes.
8. Confirm the GitHub Actions release workflow completed and the PyPI project page is correct.
