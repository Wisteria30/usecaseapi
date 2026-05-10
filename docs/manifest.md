# UseCaseAPI Manifest

UseCaseAPI Manifest is the canonical YAML catalog for a UseCaseAPI project. It is
designed to be readable by humans, strict enough for CI validation, and explicit
enough for code generation and agent planning.

Recommended file name:

```text
usecaseapi.ucase.yaml
```

Recommended extension:

```text
.ucase.yaml
```

Manifest kind:

```yaml
kind: usecaseapi.manifest/v1
```

Manifest is not OpenAPI. OpenAPI describes HTTP resources. UseCaseAPI Manifest
describes same-process application API nodes: contract name, version, input model,
output model, domain exception hierarchy, declared usecase dependencies, and source
locations.

## Commands

Export a Manifest from code:

```bash
usecaseapi manifest export composition:usecases \
  --project my-service \
  --package commerce \
  --contracts-root src/commerce \
  --implementations-root src \
  --output usecaseapi.ucase.yaml
```

Validate a Manifest:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
```

Generate Python contract and implementation skeletons from a Manifest:

```bash
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
```

This reads each `source.contract_file` and `source.implementation_file` entry and
writes the corresponding Python modules. Use `--force` when you intentionally want
to overwrite existing generated files.

Check that code and a Manifest describe the same contract catalog:

```bash
usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml
```

Render docs and graph output from a Manifest:

```bash
usecaseapi docs usecaseapi.ucase.yaml --output usecaseapi.md
usecaseapi graph usecaseapi.ucase.yaml --output usecaseapi.mmd
```

Compare two Manifests:

```bash
usecaseapi diff old.ucase.yaml new.ucase.yaml
```

## Example

```yaml
kind: usecaseapi.manifest/v1
metadata:
  name: basic
runtime:
  language: python
  python: '>=3.12,<3.15'
  protocol: usecaseapi.inprocess.async_call/v1
layout:
  contracts_root: src/commerce
  implementations_root: src
  package: commerce
usecases:
  - name: commerce.place_order
    version: 1
    key: commerce.place_order@v1
    domain: commerce
    description: Creates an order after inventory has been confirmed.
    stable: true
    deprecated: false
    tags: []
    protocol:
      kind: usecaseapi.inprocess.async_call/v1
      signature: 'async __call__(input: PlaceOrderUseCaseInput) -> PlaceOrderUseCaseOutput'
    source:
      contract_module: commerce.usecases.place_order.v1.place_order_contract
      protocol_class: PlaceOrder
      implementation_class: PlaceOrderUseCase
      implementation_file: src/commerce/usecases/place_order/v1/place_order_usecase.py
      ref: PLACE_ORDER_USECASE
      contract_file: src/commerce/usecases/place_order/v1/place_order_contract.py
    input: PlaceOrderUseCaseInput
    output: PlaceOrderUseCaseOutput
    models:
      - name: Item
        fields:
          - name: sku_id
            type: str
            required: true
          - name: quantity
            type: int
            required: true
        description: Order item requested by the caller.
      - name: PlaceOrderUseCaseInput
        fields:
          - name: user_id
            type: str
            required: true
          - name: item
            type: Item
            required: true
        description: Input required to place an order.
      - name: PlaceOrderUseCaseOutput
        fields:
          - name: order_id
            type: str
            required: true
          - name: status
            type: Literal['accepted']
            required: true
        description: Accepted order result.
    errors:
      - name: PlaceOrderError
        base: UseCaseError
        code: commerce.place_order
        fields: []
      - name: InventoryShortage
        base: PlaceOrderError
        code: commerce.place_order.inventory_shortage
        fields:
          - name: sku_id
            type: str
            required: true
          - name: requested
            type: int
            required: true
          - name: available
            type: int
            required: true
    raises:
      - PlaceOrderError
    known_errors:
      - InventoryShortage
    uses:
      - commerce.check_availability@v1
```

## Syntax

Top-level fields:

- `kind`: must be `usecaseapi.manifest/v1`.
- `metadata.name`: human-readable project name.
- `runtime.language`: `python`.
- `runtime.python`: supported Python range.
- `runtime.protocol`: `usecaseapi.inprocess.async_call/v1`.
- `layout.package`: Python package that owns the usecases.
- `layout.contracts_root`: root used when source paths are exported from code.
- `layout.implementations_root`: root used for generated implementation paths.
- `usecases`: non-empty list of versioned usecase contracts.

Usecase fields:

- `name`: stable dotted contract name, for example `commerce.place_order`.
- `version`: integer major version.
- `key`: canonical key, always `{name}@v{version}`.
- `domain`: first segment of `name`.
- `description`: context for the usecase behavior.
- `stable`: whether breaking changes should be treated conservatively.
- `deprecated`: whether this version should no longer be used.
- `superseded_by`: optional replacement key.
- `tags`: optional strings for grouping.
- `protocol.kind`: `usecaseapi.inprocess.async_call/v1`.
- `protocol.signature`: readable async call signature.
- `source`: code mapping used by agents, reviewers, and `manifest scaffold`.
- `input`: input model class name.
- `output`: output model class name.
- `models`: model declarations used to generate contract classes.
- `errors`: domain error declarations.
- `raises`: public error boundary classes.
- `known_errors`: documented leaf error classes.
- `uses`: declared usecase dependency keys.

Source fields:

- `contract_module`: import path of the generated or existing contract module.
- `protocol_class`: Protocol class name.
- `implementation_class`: callable implementation class name.
- `implementation_file`: file path generated by `manifest scaffold`.
- `ref`: exported `UseCaseRef` constant name.
- `contract_file`: file path generated by `manifest scaffold`.
- `binding_factory`: optional exported binding factory qualname.
- `binding_file`: optional file containing the binding factory.

Model fields:

- `name`: Python model class name.
- `module`: optional module where an exported model came from.
- `description`: context for Input, Output, and nested models.
- `fields`: field declarations.

Field declarations:

- `name`: Python field name.
- `type`: Python annotation expression supported by UseCaseAPI validation.
- `required`: boolean.
- `description`: optional field-level context.

Supported type expressions include `str`, `int`, `float`, `bool`, `bytes`, `Any`,
`UUID`, `date`, `datetime`, `Decimal`, `list[T]`, `dict[K, V]`, `set[T]`,
`tuple[A, B]`, `T | None`, and `Literal['value']`.

Error fields:

- `name`: Python exception class name.
- `module`: optional module where an exported error came from.
- `base`: `UseCaseError` or another error declared in the same usecase.
- `code`: stable machine-readable error code.
- `fields`: structured error payload fields.

## Writing A Manifest Before Code

When code does not exist yet, write `usecaseapi.ucase.yaml` first, then generate the
initial contract and implementation skeletons:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
```

For the v1.1 scaffold layout, set paths like this:

```yaml
layout:
  contracts_root: src/commerce
  implementations_root: src
  package: commerce
source:
  contract_module: commerce.usecases.place_order.v1.place_order_contract
  protocol_class: PlaceOrder
  implementation_class: PlaceOrderUseCase
  implementation_file: src/commerce/usecases/place_order/v1/place_order_usecase.py
  ref: PLACE_ORDER_USECASE
  contract_file: src/commerce/usecases/place_order/v1/place_order_contract.py
```

## Design Rules

Use `name + version` as the identity of a usecase contract. The full key is
`name@v{version}`.

Use `models` for model definitions that are both readable and suitable for Python
skeleton generation. Field types use a small Python-annotation-compatible subset.

Use `description` on the usecase, input model, and output model. These descriptions
carry the context needed by reviewers, documentation generators, and LLM agents.

Use real Python exception classes for domain errors. `raises` is the public catch
boundary. `known_errors` is the documented leaf-error list.

Use `uses` to declare same-process usecase dependency edges.

Use `source` to preserve code-position mapping. Agents and contributors can jump
from the Manifest to the exact contract and implementation files.

## Relationship To Other Outputs

Manifest is the canonical catalog. Markdown docs, Mermaid graph output, Python
contract skeletons, implementation skeletons, and diffs are derived from Manifest
data.
