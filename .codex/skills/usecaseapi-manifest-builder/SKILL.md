---
name: usecaseapi-manifest-builder
description: "Build UseCaseAPI Manifest YAML from conversation, validate it, and generate contract/usecase skeletons after explicit user approval. Use when a user wants to design usecaseapi.ucase.yaml, convert rough application usecase requirements into a Manifest catalog, run usecaseapi manifest validate, scaffold UseCaseAPI code, bind implementations in composition, or check Manifest/code synchronization."
---

# Usecaseapi Manifest Builder

## Overview

Create a reviewable UseCaseAPI Manifest from a conversation, validate it with the project CLI, and scaffold code only after the user explicitly approves file generation.

Skill version: `1.1.0`.

This skill targets UseCaseAPI library version `1.1.0`. Keep this skill's version equal to the UseCaseAPI library version in `pyproject.toml`. The current source of truth for this skill is the repository copy at `.codex/skills/usecaseapi-manifest-builder`, not the latest PyPI release.

Use `references/manifest-authoring.md` when writing or repairing Manifest YAML. Use `assets/usecaseapi.ucase.yaml.template` as the starting structure when no existing Manifest is present.

## Workflow

1. Inspect project context.
   - Read existing `usecaseapi.ucase.yaml`, `docs/manifest.md`, or `docs/llm-manifest-prompt.md` when present.
   - Compare `.codex/skills/usecaseapi-manifest-builder/VERSION` with `[project].version` in `pyproject.toml` when this repository is available.
   - If the installed user skill version differs from the repository skill version, self-update from the repository skill before continuing. See "Skill Version And Self-Update".
   - Verify the project has UseCaseAPI installed at the skill target version before running CLI commands. See "Library Version Check".
   - If code already exists, prefer exporting the current catalog:
     `usecaseapi manifest export composition:usecases --output usecaseapi.ucase.yaml`.
   - Do not ask the CLI for `project`, `package`, `contracts_root`, `implementations_root`, or `include_json_schema`; export is intentionally `composition:usecases` plus optional output.

2. Interview before writing YAML.
   - Ask concise questions for missing business semantics: project name, package, root path, usecase names, version, behavior boundary, inputs, outputs, domain errors, declared same-process usecase dependencies, stability, deprecation, and replacement key.
   - Ask before choosing optional domain fields, error meanings, dependency edges, or generated file locations that are not mechanically derived.
   - Use explicit assumptions only for mechanical conventions from the reference, such as class names and v1.1 scaffold paths.

3. Draft `usecaseapi.ucase.yaml`.
   - Write the Manifest with `kind: usecaseapi.manifest/v1`.
   - Include `description` for every usecase, input model, output model, nested model, and domain error when available.
   - Keep `uses` limited to same-process usecase dependencies.
   - Keep framework objects, repositories, database sessions, HTTP clients, and transaction details out of Manifest dependency edges.

4. Validate before asking for generation approval.
   - Run `usecaseapi manifest validate usecaseapi.ucase.yaml`.
   - If validation fails, fix the Manifest and rerun validation.
   - Report the exact validation command and result.

5. Request explicit approval before writing generated code.
   - Show the generated file paths that `manifest scaffold` will write or run:
     `usecaseapi manifest scaffold usecaseapi.ucase.yaml --root . --dry-run`.
   - Ask the user to approve scaffold generation.
   - Do not run a writing scaffold command until approval is given.

6. Generate and bind after approval.
   - Run `usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .`.
   - Implement the generated usecase bodies only if the user asked for implementation beyond skeletons.
   - Bind implementation factories in the project composition module.
   - Run `usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml`.

## No Unapproved Defaults

Treat unsupported or unknown behavior as a question or explicit error, not as a fallback.

Allowed mechanical conventions:

- `name`: `{package}.{usecase_name}`
- `key`: `{name}@v{version}`
- `contract_module`: `{package}.usecases.{usecase_name}.v{version}.{usecase_name}_contract`
- `implementation_file`: `{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_usecase.py`
- `contract_file`: `{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_contract.py`
- `protocol_class`: PascalCase usecase name without the `UseCase` suffix
- `implementation_class`: PascalCase usecase name plus `UseCase`
- `ref`: upper snake case usecase name plus `_USECASE`
- input/output: PascalCase usecase name plus `UseCaseInput` / `UseCaseOutput`

Ask the user before inventing:

- business fields;
- enum values;
- domain error semantics;
- dependency edges;
- deprecation or replacement policy;
- overwrite behavior;
- implementation logic.

## Validation Commands

Use these commands from the project root:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root . --dry-run
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml
```

If the project uses `uv`, run commands through `uv run`, for example:

```bash
uv run usecaseapi manifest validate usecaseapi.ucase.yaml
```

## Library Version Check

Before using `usecaseapi` commands, verify the installed library version:

```bash
uv run python -c "from importlib.metadata import version; print(version('usecaseapi'))"
```

If that command reports `PackageNotFoundError` inside the UseCaseAPI source checkout, install the local development environment:

```bash
uv sync --extra dev
```

If that command reports `PackageNotFoundError` inside a downstream project, install `1.1.0` only from an explicit development source, such as a user-provided local checkout path or approved Git reference:

```bash
uv add --editable /path/to/usecaseapi
```

Do not install `usecaseapi==1.0.0` from PyPI for this skill. If no `1.1.0` development source is known, stop and ask for the source path or approved Git reference. Do not choose `pip`, `poetry`, `pdm`, PyPI `1.0.0`, or another installer without project evidence or user approval.

If the installed version differs from `1.1.0`, stop and report the mismatch before generating or scaffolding. Ask whether to update the project dependency or point the project at the local `1.1.0` development source. Do not continue with a version mismatch.

## Skill Version And Self-Update

Use `.codex/skills/usecaseapi-manifest-builder/VERSION` as the skill version. It must match `[project].version` in `pyproject.toml`.

Check the library version from the repository root:

```bash
uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
```

Check the repository skill version:

```bash
cat .codex/skills/usecaseapi-manifest-builder/VERSION
```

If the active user skill is older or differs from the repository skill, update the user skill from the repository copy:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills/usecaseapi-manifest-builder"
cp -R .codex/skills/usecaseapi-manifest-builder/. "${CODEX_HOME:-$HOME/.codex}/skills/usecaseapi-manifest-builder/"
```

Only copy from this repository's `.codex/skills/usecaseapi-manifest-builder`. Do not update from PyPI `1.0.0` docs or another generated copy when working against library version `1.1.0`.

## Completion Evidence

Before claiming the task is complete, report:

- the Manifest file path;
- skill version and library version comparison;
- UseCaseAPI library version check result;
- validation command and result;
- scaffold command result, or that generation was not approved;
- binding changes, if any;
- synchronization check command and result, if code was generated or changed.
