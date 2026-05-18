# UseCaseAPI Manifest

UseCaseAPI Manifest v2 is a dedicated UseCaseAPI profile on top of an OpenAPI
3.1.0 document. The recommended file name is:

```text
usecaseapi.yaml
```

The root document must be valid OpenAPI 3.1.0 and must include the UseCaseAPI
profile extension:

```yaml
openapi: 3.1.0
x-usecaseapi:
  version: 3.1.0
  profile: usecaseapi.openapi
  manifestKind: usecaseapi.openapi.profile/3.1.0
```

OpenAPI fields describe the visible call surface for generic tools. UseCaseAPI
fields under `x-usecaseapi` describe same-process semantics, Python bindings,
dependency edges, source mapping, and domain error hierarchy.

## Commands

Export a Manifest from code:

```bash
usecaseapi manifest export composition:usecases --output usecaseapi.yaml
```

Validate a Manifest:

```bash
usecaseapi manifest validate usecaseapi.yaml
```

Generate Python contract, implementation, and pytest skeletons:

```bash
usecaseapi manifest scaffold usecaseapi.yaml --root .
```

Check that code and a Manifest describe the same contract catalog:

```bash
usecaseapi manifest check-sync composition:usecases usecaseapi.yaml
```

Run the same local contract check used by CI:

```bash
usecaseapi manifest ci --target composition:usecases --manifest usecaseapi.yaml
```

Compare two committed Manifest files for version immutability:

```bash
usecaseapi manifest guard base.yaml head.yaml
```

Render derived outputs:

```bash
usecaseapi docs usecaseapi.yaml --output usecaseapi.md
usecaseapi graph usecaseapi.yaml --output usecaseapi.mmd
usecaseapi diff old.yaml new.yaml
```

## Mapping Rules

Each usecase is represented as a `post` Operation under `paths`:

```yaml
paths:
  /_usecases/commerce.place_order/v1/call:
    post:
      operationId: commerce_place_order_v1_call
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/CommercePlaceOrderV1PlaceOrderUseCaseInput"
      responses:
        "200":
          description: PlaceOrderUseCaseOutput result.
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/CommercePlaceOrderV1PlaceOrderUseCaseOutput"
      x-usecaseapi:
        kind: usecase
        key: commerce.place_order@v1
        name: commerce.place_order
        version: 1
        protocol: usecaseapi.inprocess.async_call.v1
```

UseCaseAPI uses the OpenAPI standard fields as the generic UI layer:

- `paths`: documented usecase call operations.
- `operationId`: stable operation name for generic tools.
- `requestBody`: input model schema.
- `responses.200`: output model schema.
- `responses.default`: documented domain error envelopes.
- `components.schemas`: input, output, nested model, and error payload schemas.
- `tags`, `summary`, and `description`: human-facing documentation.

UseCaseAPI-specific semantics live under `x-usecaseapi`:

- root `x-usecaseapi`: profile version, runtime defaults, Python roots, protocol
  definitions, and domain error hierarchy.
- operation `x-usecaseapi.key`: canonical usecase key, always
  `{name}@v{version}`.
- operation `x-usecaseapi.lifecycle`: stability, deprecation, and replacement key.
- operation `x-usecaseapi.semantics`: command/query metadata.
- operation `x-usecaseapi.uses`: same-process dependency edges.
- operation `x-usecaseapi.bindings.python`: source mapping used by scaffold and
  synchronization checks.
- schema `x-usecaseapi`: canonical model role and Python class binding.

## Python Binding Shape

The scaffold command reads Python binding metadata from each operation:

```yaml
x-usecaseapi:
  bindings:
    python:
      signature: "async __call__(input: PlaceOrderUseCaseInput) -> PlaceOrderUseCaseOutput"
      contract:
        module: commerce.usecases.place_order.v1.place_order_contract
        file: src/commerce/usecases/place_order/v1/place_order_contract.py
        protocolClass: PlaceOrder
        ref: PLACE_ORDER_USECASE
      implementation:
        class: PlaceOrderUseCase
        file: src/commerce/usecases/place_order/v1/place_order_usecase.py
```

Those values are explicit. If a required source mapping is missing, validation or
generation fails rather than inventing a path.

## Domain Errors

Domain errors are represented twice:

- OpenAPI `components.schemas` describes serialized payload and envelope schemas
  for documentation and generic rendering.
- root `x-usecaseapi.components.errors` preserves the Python exception hierarchy,
  stable error codes, and payload/envelope schema references.

## Validation

Validation has two stages:

1. Check the document-level OpenAPI profile requirements: `openapi: 3.1.0`,
   `info`, `paths`, `components`, and root `x-usecaseapi`.
2. Normalize the operations into UseCaseAPI semantic metadata and check contract
   names, keys, model references, type expressions, error boundaries, dependency
   edges, and Python source bindings.

## CI Contract Check

Commit `usecaseapi.yaml` as the canonical contract file for the repository.
Derived documentation and graphs can be regenerated, but `usecaseapi.yaml`
is the reviewable source of truth for the application contract catalog.

The CI command validates that file, checks that it still matches the target
UseCaseAPI composition, and optionally compares it with a base Manifest:

```bash
usecaseapi manifest ci --target composition:usecases --manifest usecaseapi.yaml
usecaseapi manifest guard base.yaml head.yaml
```

The immutability rule is intentionally simple: the same usecase name with the
same version cannot be changed or removed. Add a new version for breaking
changes. Adding new usecases or new versions is allowed.

The GitHub Action is a composite wrapper around the CLI. Install Python,
UseCaseAPI, and the repository dependencies before calling it; the action does
not install project dependencies for you.

```yaml
name: Contracts

on:
  pull_request:

jobs:
  contract-check:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - uses: astral-sh/setup-uv@v8.1.0
      - run: uv sync --frozen
      - run: echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
      - uses: Wisteria30/usecaseapi/actions/contract-check@vX
        with:
          target: composition:usecases
          manifest: usecaseapi.yaml
          comment-on-pr: "false"
```

Use a released tag or commit SHA instead of `vX`. Repositories executing pull
request head code should keep `permissions.contents: read` and
`comment-on-pr: "false"` unless they intentionally allow the action to write PR
comments. When comments are intentionally enabled, grant the minimal additional
permission required by the workflow host.

## Writing A Manifest Before Code

When code does not exist yet, write `usecaseapi.yaml` first, then generate the
initial skeletons:

```bash
usecaseapi manifest validate usecaseapi.yaml
usecaseapi manifest scaffold usecaseapi.yaml --root .
```

For a complete generated example, see `examples/basic/usecaseapi.yaml`.
