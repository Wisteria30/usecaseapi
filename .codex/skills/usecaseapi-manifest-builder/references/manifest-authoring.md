# UseCaseAPI Manifest Authoring Reference

Use this reference when turning conversation requirements into `usecase.yaml` or migrating a legacy semantic Manifest into the OpenAPI-profile Manifest.

Skill version: `2.1.1`.

Target UseCaseAPI library version: `2.1.1`.

The skill version must match `[project].version` in `pyproject.toml`. If the active user skill differs from `.codex/skills/usecaseapi-manifest-builder/VERSION`, update the active skill by copying the repository skill directory into `${CODEX_HOME:-$HOME/.codex}/skills`.

## Purpose

UseCaseAPI Manifest is an OpenAPI 3.1.0 YAML document with UseCaseAPI-specific semantics in `x-usecaseapi`. It documents same-process application usecase APIs. It is not an HTTP framework, RPC framework, dependency injection container, transaction manager, or DDD architecture generator.

The Manifest describes:

- OpenAPI operation surface for each usecase call;
- root UseCaseAPI profile metadata;
- Python runtime roots and package;
- usecase name, version, key, tags, stability, deprecation, and replacement;
- behavior description;
- Python source module, file, class, and ref mapping;
- input/output schemas and Python model bindings;
- nested schemas;
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
- stable/deprecated/supersededBy/tags.

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

If the package is not installed inside a downstream project, install `2.1.1` only from an explicit development source, such as a user-provided local checkout path or approved Git reference:

```bash
uv add --editable /path/to/usecaseapi
```

Do not install an older UseCaseAPI release for this skill. If another version is installed, do not continue with Manifest generation or scaffold. Report the mismatch and ask whether to align the project dependency with the local `2.1.1` development source.

Use this current export shape:

```bash
usecaseapi manifest export composition:usecases --output usecase.yaml
```

Do not pass `project`, `package`, `contracts_root`, `implementations_root`, or `include_json_schema` to the CLI export command.

Validate and generate:

```bash
usecaseapi manifest validate usecase.yaml
usecaseapi manifest scaffold usecase.yaml --root . --dry-run
usecaseapi manifest scaffold usecase.yaml --root .
usecaseapi manifest check-sync composition:usecases usecase.yaml
```

## Scaffold Layout

Target the v2.1 scaffold layout:

```text
{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_contract.py
{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_usecase.py
```

Use these conventions unless the user specifies a different accepted layout:

- `x-usecaseapi.runtimes.python.package`: Python import package and filesystem package that owns usecases.
- `x-usecaseapi.runtimes.python.roots.contracts`: usually `{root}/{package}`.
- `x-usecaseapi.runtimes.python.roots.implementations`: usually `{root}`.
- `x-usecaseapi.runtimes.python.roots.tests`: usually `tests`.
- operation path: `/_usecases/{package}.{usecase_name}/v{version}/call`.
- `operationId`: `{package}_{usecase_name}_v{version}_call`.
- operation `x-usecaseapi.key`: `{package}.{usecase_name}@v{version}`.
- operation `x-usecaseapi.name`: `{package}.{usecase_name}`.
- operation `x-usecaseapi.protocol`: `usecaseapi.inprocess.async_call.v1`.
- operation `x-usecaseapi.bindings.python.contract.module`: `{package}.usecases.{usecase_name}.v{version}.{usecase_name}_contract`.
- operation `x-usecaseapi.bindings.python.implementation.file`: `{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_usecase.py`.
- operation `x-usecaseapi.bindings.python.contract.file`: `{root}/{package}/usecases/{usecase_name}/v{version}/{usecase_name}_contract.py`.
- operation `x-usecaseapi.bindings.python.contract.protocolClass`: PascalCase usecase name without the `UseCase` suffix.
- operation `x-usecaseapi.bindings.python.implementation.class`: PascalCase usecase name plus `UseCase`.
- operation `x-usecaseapi.bindings.python.contract.ref`: upper snake case usecase name plus `_USECASE`.
- operation `x-usecaseapi.input.pythonName`: PascalCase usecase name plus `UseCaseInput`.
- operation `x-usecaseapi.output.pythonName`: PascalCase usecase name plus `UseCaseOutput`.

## Required YAML Shape

Use `assets/usecase.yaml.template` for the full editable skeleton. A valid Manifest must have this root shape:

```yaml
openapi: 3.1.0
info:
  title: project-name
  version: 1.0.0
paths:
  /_usecases/package_name.usecase_name/v1/call:
    post:
      operationId: package_name_usecase_name_v1_call
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/PackageNameUsecaseNameV1UsecaseNameUseCaseInput"
      responses:
        "200":
          description: UsecaseNameUseCaseOutput result.
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/PackageNameUsecaseNameV1UsecaseNameUseCaseOutput"
      x-usecaseapi:
        kind: usecase
        key: package_name.usecase_name@v1
        name: package_name.usecase_name
        version: 1
        action: call
        lifecycle:
          stability: stable
          deprecated: false
        protocol: usecaseapi.inprocess.async_call.v1
        input:
          pythonName: UsecaseNameUseCaseInput
          schema: "#/components/schemas/PackageNameUsecaseNameV1UsecaseNameUseCaseInput"
        output:
          pythonName: UsecaseNameUseCaseOutput
          schema: "#/components/schemas/PackageNameUsecaseNameV1UsecaseNameUseCaseOutput"
        errors:
          raises: []
          known: []
        uses: {}
        bindings:
          python:
            signature: "async __call__(input: UsecaseNameUseCaseInput) -> UsecaseNameUseCaseOutput"
            contract:
              module: package_name.usecases.usecase_name.v1.usecase_name_contract
              file: src/package_name/usecases/usecase_name/v1/usecase_name_contract.py
              protocolClass: UsecaseName
              ref: USECASE_NAME_USECASE
            implementation:
              class: UsecaseNameUseCase
              file: src/package_name/usecases/usecase_name/v1/usecase_name_usecase.py
components:
  schemas: {}
x-usecaseapi:
  version: 3.1.0
  profile: usecaseapi.openapi
  manifestKind: usecaseapi.openapi.profile/3.1.0
  defaults:
    runtime: python
    protocol: usecaseapi.inprocess.async_call.v1
  runtimes:
    python:
      language: python
      version: ">=3.12,<3.15"
      package: package_name
      roots:
        contracts: src/package_name
        implementations: src
        tests: tests
  protocols:
    usecaseapi.inprocess.async_call.v1:
      type: inprocess
      interaction: requestReply
      action: call
      async: true
      serialization: none
  components:
    errors: {}
```

## Field Type Expressions

Supported expressions:

- `str`, `int`, `float`, `bool`, `bytes`, `Any`;
- `UUID`, `date`, `datetime`, `Decimal`;
- `list[T]`, `dict[K, V]`, `set[T]`, `tuple[A, B]`;
- `T | None`;
- `Literal['value']`;
- model names declared in the same usecase.

## Description Rules

Every usecase should include one sentence in OpenAPI `summary` and `description` that explains behavior and boundary. Manifest scaffold renders the usecase description as generated module/class/protocol docstrings and `Contract(description=...)`.

Every input model, output model, nested model, and domain error should include a description when the conversation provides business meaning. Add field descriptions when they clarify caller obligations, result semantics, or error payload meaning.

## Error Rules

Use root `x-usecaseapi.components.errors` for structured domain exceptions. Use operation `x-usecaseapi.errors.raises` for public catch boundary classes. Use operation `x-usecaseapi.errors.known` for documented leaf errors.

Error `code` values must live under the usecase name, for example:

```text
commerce.place_order.inventory_shortage
```

`base` must be `UseCaseError` or another error declared under root `x-usecaseapi.components.errors`. Known errors must be covered by the declared public boundary.

## Dependency Rules

Use operation `x-usecaseapi.uses` only for declared same-process usecase calls:

```yaml
uses:
  check_availability:
    key: commerce.check_availability@v1
    required: true
```

Do not put database sessions, repositories, HTTP clients, framework objects, transaction details, storage backends, or external services into `uses`.

## Approval Rule

Run validation before requesting scaffold approval. Use `--dry-run` to show planned files. Run the writing scaffold command only after the user explicitly approves generation.
