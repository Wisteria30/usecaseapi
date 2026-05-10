# PyPI Publishing Readiness

This repository is prepared for PyPI publishing through GitHub Actions and PyPI Trusted Publishing.

## Repository-side setup

- Package metadata lives in `pyproject.toml`.
- The package builds with Hatchling through `uv build`.
- Runtime dependencies are Pydantic v2 and Typer.
- `py.typed` is included in the wheel for typed consumers.
- `exclude-newer = "P7D"` is configured for uv dependency resolution.
- `trusted-publishing = "always"` is configured so release publishing fails if OIDC publishing is unavailable.
- `pyproject.toml` `[project].version` is the release source of truth.
- `.github/workflows/release.yml` creates `v{version}` when the project version changes on `main`.
- `.github/workflows/release.yml` creates a GitHub Release with generated notes and distribution artifacts before publishing.
- `.github/workflows/release.yml` validates tests, coverage, typing, linting, metadata, wheel install, source distribution install, and then publishes.
- `.github/workflows/ci.yml` reports coverage in the GitHub Actions job summary for pull requests.

## Release workflow contract

The release workflow watches `main` and creates an annotated `v{version}` tag
when `pyproject.toml` `[project].version` changes. It then creates a GitHub
Release for that tag before publishing to PyPI. It also supports pushed tags
matching `v*` and manual dispatch.

The PyPI Trusted Publisher should match:

- Owner: `Wisteria30`
- Repository: `usecaseapi`
- Workflow: `release.yml`
- Environment: `pypi`

## Human tasks before first publish

1. Confirm `https://pypi.org/project/usecaseapi/` and `https://test.pypi.org/project/usecaseapi/` are still unclaimed.
2. Create or choose the PyPI account or organization that will own the package.
3. Add a PyPI Trusted Publisher for this GitHub repository.
4. Create the GitHub `pypi` environment in repository settings.
5. Decide whether the `pypi` environment requires manual approval.
6. Confirm project ownership metadata, maintainer identity, and support expectations.
7. Update the release version in `pyproject.toml`.
8. Prepare release notes.
9. Merge the version bump to `main`; GitHub Actions creates the release tag, creates the GitHub Release, and publishes.
10. Review the GitHub Release, published PyPI page, verified project links, files, and installation instructions.

## Local validation command

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
