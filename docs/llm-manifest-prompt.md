# LLM Prompt For UseCaseAPI Manifest Design

Use this prompt when a conversation has produced rough requirements and you want an
LLM to converge them into a UseCaseAPI Manifest. The intended output is a
reviewable `usecaseapi.yaml` that can be validated and used to generate
initial Python contract, implementation, and pytest skeletons.

## Prompt

````text
You are designing a UseCaseAPI Manifest for a Python project.

UseCaseAPI treats same-process application usecases as versioned contracts. It is
not an HTTP framework, RPC framework, dependency injection container, transaction
manager, or DDD architecture generator. It defines the public application API
surface for usecases: stable name, version, input model, output model, domain
errors, declared usecase dependencies, and source file locations.

Your goal is to produce a complete `usecaseapi.yaml` for the requested
usecases. The file must follow the UseCaseAPI Manifest v2 OpenAPI profile syntax
and target the scaffold layout:

{root}/{package}/usecases/{usecase}/v{version}/{usecase}_contract.py
{root}/{package}/usecases/{usecase}/v{version}/{usecase}_usecase.py

Use these source conventions:

- `x-usecaseapi.runtimes.python.package`: the Python import package and filesystem package that owns the usecases.
- `x-usecaseapi.runtimes.python.roots.contracts`: usually `{root}/{package}`.
- `x-usecaseapi.runtimes.python.roots.implementations`: usually `{root}`.
- `x-usecaseapi.runtimes.python.roots.tests`: usually `tests`.
- `name`: `{package}.{usecase}` unless a narrower package/module decision is
  explicitly provided.
- `key`: `{name}@v{version}`.
- operation `x-usecaseapi.bindings.python.contract.module`:
  `{package}.usecases.{usecase}.v{version}.{usecase}_contract`
- operation `x-usecaseapi.bindings.python.implementation.file`:
  `{root}/{package}/usecases/{usecase}/v{version}/{usecase}_usecase.py`
- operation `x-usecaseapi.bindings.python.contract.file`:
  `{root}/{package}/usecases/{usecase}/v{version}/{usecase}_contract.py`
- operation `x-usecaseapi.bindings.python.contract.protocolClass`: PascalCase usecase name without the `UseCase` suffix.
- operation `x-usecaseapi.bindings.python.implementation.class`: PascalCase usecase name plus `UseCase`.
- operation `x-usecaseapi.bindings.python.contract.ref`: upper snake case usecase name plus `_USECASE`.
- operation `x-usecaseapi.input.pythonName`: PascalCase usecase name plus `UseCaseInput`.
- operation `x-usecaseapi.output.pythonName`: PascalCase usecase name plus `UseCaseOutput`.

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

- Use root `x-usecaseapi.components.errors` for structured domain exceptions.
- Use operation `x-usecaseapi.errors.raises` for the public catch boundary.
- Use operation `x-usecaseapi.errors.known` for documented leaf errors.
- Error `code` values must live under the usecase name, for example
  `commerce.place_order.inventory_shortage`.

Dependency edges:

- Use operation `x-usecaseapi.uses` only for declared same-process usecase calls.
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
2. `usecaseapi.yaml` section containing one YAML code block.
3. `Assumptions` section only for decisions that were not directly stated.
4. `Next Commands` section with:

```bash
usecaseapi manifest validate usecaseapi.yaml
usecaseapi manifest scaffold usecaseapi.yaml --root .
```

Minimal Manifest shape:

```yaml
openapi: 3.1.0
info:
  title: example
  version: 1.0.0
paths:
  /_usecases/package_name.usecase_name/v1/call:
    post:
      operationId: package_name_usecase_name_v1_call
      summary: One sentence describing the usecase behavior and boundary.
      description: One sentence describing the usecase behavior and boundary.
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
  schemas:
    PackageNameUsecaseNameV1UsecaseNameUseCaseInput:
      title: UsecaseNameUseCaseInput
      type: object
      additionalProperties: false
      required:
        - example_id
      properties:
        example_id:
          type: string
          description: Stable identifier for the example entity.
      x-usecaseapi:
        kind: input
        bindings:
          python:
            class: UsecaseNameUseCaseInput
    PackageNameUsecaseNameV1UsecaseNameUseCaseOutput:
      title: UsecaseNameUseCaseOutput
      type: object
      additionalProperties: false
      required:
        - accepted
      properties:
        accepted:
          type: boolean
          description: Whether the request was accepted.
      x-usecaseapi:
        kind: output
        bindings:
          python:
            class: UsecaseNameUseCaseOutput
x-usecaseapi:
  version: 3.1.0
  profile: usecaseapi.openapi
  manifestKind: usecaseapi.openapi.profile/3.1.0
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
````

## Validation And Code Generation

After the LLM produces YAML:

```bash
usecaseapi manifest validate usecaseapi.yaml
usecaseapi manifest scaffold usecaseapi.yaml --root .
```

If code already exists, export and compare:

```bash
usecaseapi manifest export composition:usecases --output usecaseapi.yaml
usecaseapi manifest check-sync composition:usecases usecaseapi.yaml
```
