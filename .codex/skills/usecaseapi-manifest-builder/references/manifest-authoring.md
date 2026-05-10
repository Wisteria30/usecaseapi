# UseCaseAPI Manifest Authoring Reference

Use this reference when turning conversation requirements into `usecaseapi.ucase.yaml`.

Skill version: `1.1.0`.

Target UseCaseAPI library version: `1.1.0`.

The skill version must match `[project].version` in `pyproject.toml`. If the active user skill differs from `.codex/skills/usecaseapi-manifest-builder/VERSION`, update the active skill by copying the repository skill directory into `${CODEX_HOME:-$HOME/.codex}/skills`.

## Purpose

UseCaseAPI Manifest is a YAML catalog for same-process application usecase APIs. It is not OpenAPI, RPC, dependency injection, a transaction manager, or an architecture generator.

The Manifest describes:

- project metadata;
- runtime protocol;
- layout;
- usecase name, version, key, namespace, tags, stability, deprecation, and replacement;
- behavior description;
- source module, file, class, and ref mapping;
- input/output models and fields;
- nested models;
- domain error hierarchy;
- declared same-process usecase dependencies.

## Required Conversation Inputs

Ask concise questions until these are known:

- project name;
- root path, commonly `src`;
- package name;
- usecase names;
- version for each usecase;
- behavior and boundary for each usecase;
- input fields, type expressions, required status, and field descriptions;
- output fields, type expressions, required status, and field descriptions;
- nested models;
- domain errors, base classes, codes, payload fields, and public catch boundary;
- declared same-process usecase dependencies;
- stable/deprecated/superseded_by/tags.

Do not silently invent business fields, dependency edges, error semantics, enum values, or generated overwrite behavior.

## CLI Contract

Before running the CLI, verify the installed package:

```bash
uv run python -c "from importlib.metadata import version; print(version('usecaseapi'))"
```

If the package is not installed inside the UseCaseAPI source checkout, install the local development environment:

```bash
uv sync --extra dev
```

If the package is not installed inside a downstream project, install `1.1.0` only from an explicit development source, such as a user-provided local checkout path or approved Git reference:

```bash
uv add --editable /path/to/usecaseapi
```

Do not install `usecaseapi==1.0.0` from PyPI for this skill. If another version is installed, do not continue with Manifest generation or scaffold. Report the mismatch and ask whether to align the project dependency with the local `1.1.0` development source.

Use this current export shape:

```bash
usecaseapi manifest export composition:usecases --output usecaseapi.ucase.yaml
```

Do not pass `project`, `package`, `contracts_root`, `implementations_root`, or `include_json_schema` to the CLI export command.

Validate and generate:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root . --dry-run
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml
```

## Scaffold Layout

Target the v1.1 scaffold layout:

```text
{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_contract.py
{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_usecase.py
```

Use these conventions unless the user specifies a different accepted layout:

- `layout.package`: Python import package and filesystem package that owns usecases.
- `layout.contracts_root`: usually `{root}/{package}`.
- `layout.implementations_root`: usually `{root}`.
- `name`: `{package}.{usecase_name}`.
- `key`: `{name}@v{version}`.
- `source.contract_module`: `{package}.usecases.{usecase_name}.v{version}.{usecase_name}_contract`.
- `source.implementation_file`: `{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_usecase.py`.
- `source.contract_file`: `{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_contract.py`.
- `source.protocol_class`: PascalCase usecase name without the `UseCase` suffix.
- `source.implementation_class`: PascalCase usecase name plus `UseCase`.
- `source.ref`: upper snake case usecase name plus `_USECASE`.
- `input`: PascalCase usecase name plus `UseCaseInput`.
- `output`: PascalCase usecase name plus `UseCaseOutput`.

## Required YAML Shape

```yaml
kind: usecaseapi.manifest/v1
metadata:
  name: project-name
runtime:
  language: python
  python: '>=3.12,<3.15'
  protocol: usecaseapi.inprocess.async_call/v1
layout:
  contracts_root: src/package_name
  implementations_root: src
  package: package_name
usecases:
  - name: package_name.usecase_name
    version: 1
    key: package_name.usecase_name@v1
    description: One sentence describing the usecase behavior and boundary.
    stable: true
    deprecated: false
    tags: []
    protocol:
      kind: usecaseapi.inprocess.async_call/v1
      signature: 'async __call__(input: UsecaseNameUseCaseInput) -> UsecaseNameUseCaseOutput'
    source:
      contract_module: package_name.usecases.usecase_name.v1.usecase_name_contract
      protocol_class: UsecaseName
      implementation_class: UsecaseNameUseCase
      implementation_file: src/package_name/usecases/usecase_name/v1/usecase_name_usecase.py
      ref: USECASE_NAME_USECASE
      contract_file: src/package_name/usecases/usecase_name/v1/usecase_name_contract.py
    input: UsecaseNameUseCaseInput
    output: UsecaseNameUseCaseOutput
    models:
      - name: UsecaseNameUseCaseInput
        description: One sentence describing caller input.
        fields:
          - name: example_id
            type: str
            required: true
            description: Stable identifier for the example entity.
      - name: UsecaseNameUseCaseOutput
        description: One sentence describing the result.
        fields:
          - name: accepted
            type: bool
            required: true
            description: Whether the request was accepted.
    errors: []
    raises: []
    known_errors: []
    uses: []
```

## Field Type Expressions

Supported expressions:

- `str`, `int`, `float`, `bool`, `bytes`, `Any`;
- `UUID`, `date`, `datetime`, `Decimal`;
- `list[T]`, `dict[K, V]`, `set[T]`, `tuple[A, B]`;
- `T | None`;
- `Literal['value']`;
- model names declared in the same usecase `models` list.

## Description Rules

Every usecase should include one sentence that explains behavior and boundary. Manifest scaffold renders the usecase description as generated module/class/protocol docstrings and `Contract(description=...)`.

Every input model, output model, nested model, and domain error should include a description when the conversation provides business meaning. Add field descriptions when they clarify caller obligations, result semantics, or error payload meaning.

## Error Rules

Use `errors` for structured domain exceptions. Use `raises` for public catch boundary classes. Use `known_errors` for documented leaf errors.

Error `code` values must live under the usecase name, for example:

```text
commerce.place_order.inventory_shortage
```

`base` must be `UseCaseError` or another error declared in the same usecase. `known_errors` must be covered by `raises`.

## Dependency Rules

Use `uses` only for declared same-process usecase calls:

```yaml
uses:
  - commerce.check_availability@v1
```

Do not put database sessions, repositories, HTTP clients, framework objects, transaction details, storage backends, or external services into `uses`.

## Approval Rule

Run validation before requesting scaffold approval. Use `--dry-run` to show planned files. Run the writing scaffold command only after the user explicitly approves generation.
