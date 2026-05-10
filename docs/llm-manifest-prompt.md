# LLM Prompt For UseCaseAPI Manifest Design

Use this prompt when a conversation has produced rough requirements and you want an
LLM to converge them into a UseCaseAPI Manifest. The intended output is a
reviewable `usecaseapi.ucase.yaml` that can be validated and used to generate
initial Python contract and implementation skeletons.

## Prompt

````text
You are designing a UseCaseAPI Manifest for a Python project.

UseCaseAPI treats same-process application usecases as versioned contracts. It is
not an HTTP framework, RPC framework, dependency injection container, transaction
manager, or DDD architecture generator. It defines the public application API
surface for usecases: stable name, version, input model, output model, domain
errors, declared usecase dependencies, and source file locations.

Your goal is to produce a complete `usecaseapi.ucase.yaml` for the requested
usecases. The file must follow the UseCaseAPI Manifest v1 syntax below and target
the v1.1 scaffold layout:

{root}/{package}/usecases/{usecase}/v{version}/{usecase}_contract.py
{root}/{package}/usecases/{usecase}/v{version}/{usecase}_usecase.py

Use these source conventions:

- `layout.package`: the Python import package and filesystem package that owns the usecases.
- `layout.contracts_root`: usually `{root}/{package}`.
- `layout.implementations_root`: usually `{root}`.
- `name`: `{package}.{usecase}` unless a narrower package/module decision is
  explicitly provided.
- `key`: `{name}@v{version}`.
- `source.contract_module`:
  `{package}.usecases.{usecase}.v{version}.{usecase}_contract`
- `source.implementation_file`:
  `{root}/{package}/usecases/{usecase}/v{version}/{usecase}_usecase.py`
- `source.contract_file`:
  `{root}/{package}/usecases/{usecase}/v{version}/{usecase}_contract.py`
- `source.protocol_class`: PascalCase usecase name without the `UseCase` suffix.
- `source.implementation_class`: PascalCase usecase name plus `UseCase`.
- `source.ref`: upper snake case usecase name plus `_USECASE`.
- `input`: PascalCase usecase name plus `UseCaseInput`.
- `output`: PascalCase usecase name plus `UseCaseOutput`.

Every usecase must include:

- `description`: one sentence explaining the usecase behavior and boundary.
  UseCaseAPI renders this as the generated contract module docstring, Protocol
  docstring, implementation module docstring, implementation class docstring, and
  `Contract(description=...)`.
- input model `description`: one sentence explaining what the caller provides.
- output model `description`: one sentence explaining what the caller receives.
- all input and output fields with `name`, `type`, `required`, and field
  `description` when it clarifies business meaning.

Supported field type expressions:

- `str`, `int`, `float`, `bool`, `bytes`, `Any`
- `UUID`, `date`, `datetime`, `Decimal`
- `list[T]`, `dict[K, V]`, `set[T]`, `tuple[A, B]`
- `T | None`
- `Literal['value']`
- other model names declared in the same usecase `models` list

Domain errors:

- Use `errors` for structured domain exceptions.
- Use `raises` for the public catch boundary.
- Use `known_errors` for documented leaf errors.
- Error `code` values must live under the usecase name, for example
  `commerce.place_order.inventory_shortage`.

Dependency edges:

- Use `uses` only for declared same-process usecase calls.
- Do not put database sessions, repositories, HTTP clients, framework objects, or
  transaction details into `uses`.
- If one usecase needs another usecase in the same business capability, keep them
  in the same package.

Ask clarification questions before producing YAML if any of these are missing or
ambiguous:

- project name;
- root path, for example `src`;
- package name;
- usecase name;
- version;
- usecase behavior and boundary;
- input fields, types, and required/optional status;
- output fields, types, and required/optional status;
- domain errors and error payload fields;
- declared usecase dependencies;
- whether the usecase should be marked deprecated or superseded.

If only a few details are missing, ask concise questions first. If enough
information is available, produce the YAML and list explicit assumptions after it.
Do not silently invent business fields, dependency edges, or error semantics.

Output format:

1. `Questions` section only when clarification is required.
2. `usecaseapi.ucase.yaml` section containing one YAML code block.
3. `Assumptions` section only for decisions that were not directly stated.
4. `Next Commands` section with:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
```

Manifest syntax:

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
````

## Validation And Code Generation

After the LLM produces YAML:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
```

If code already exists, export and compare:

```bash
usecaseapi manifest export composition:usecases --output usecaseapi.ucase.yaml
usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml
```
