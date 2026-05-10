# UseCaseAPI Manifest

UseCaseAPI Manifest is the canonical YAML catalog for a UseCaseAPI project. It is designed to be readable by humans, strict enough for CI validation, and explicit enough for code generation and agent planning.

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

Manifest is not OpenAPI. OpenAPI describes HTTP resources. UseCaseAPI Manifest describes same-process application API nodes: contract name, version, input model, output model, domain exception hierarchy, declared usecase dependencies, and source locations.

## Commands

Export a Manifest from code:

```bash
usecaseapi manifest export app.composition:usecases \
  --project my-service \
  --package app \
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

Check that code and a Manifest describe the same contract catalog:

```bash
usecaseapi manifest check-sync app.composition:usecases usecaseapi.ucase.yaml
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
  name: checkout-service
runtime:
  language: python
  python: '>=3.12,<3.15'
  protocol: usecaseapi.inprocess.async_call/v1
layout:
  package: app
  contracts_root: app/contracts
  implementations_root: app/usecases
usecases:
  - name: orders.place_order
    version: 1
    key: orders.place_order@v1
    domain: orders
    description: Creates an order after inventory has been confirmed.
    stable: true
    deprecated: false
    protocol:
      kind: usecaseapi.inprocess.async_call/v1
      signature: 'async __call__(input: Input) -> Output'
    source:
      contract_file: app/contracts/orders/place_order/v1.py
      implementation_file: app/usecases/orders/place_order.py
      contract_module: app.contracts.orders.place_order.v1
      protocol_class: PlaceOrder
      implementation_class: PlaceOrderImpl
      ref: PLACE_ORDER
    input: Input
    output: Output
    models:
      - name: Item
        fields:
          - name: sku_id
            type: str
            required: true
          - name: quantity
            type: int
            required: true
      - name: Input
        fields:
          - name: user_id
            type: str
            required: true
          - name: item
            type: Item
            required: true
      - name: Output
        fields:
          - name: order_id
            type: str
            required: true
          - name: status
            type: Literal['accepted']
            required: true
    errors:
      - name: PlaceOrderError
        base: UseCaseError
        code: orders.place_order
        fields: []
      - name: InventoryShortage
        base: PlaceOrderError
        code: orders.place_order.inventory_shortage
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
      - inventory.check_availability@v1
```

## Design Rules

Use `name + version` as the identity of a usecase contract. The full key is `name@v{version}`.

Use `models` for model definitions that are both readable and suitable for Python skeleton generation. Field types use a small Python-annotation-compatible subset such as `str`, `int`, `bool`, `list[Item]`, `dict[str, Any]`, `Item | None`, and `Literal['accepted']`.

Use real Python exception classes for domain errors. `raises` is the public catch boundary. `known_errors` is the documented leaf-error list.

Use `uses` to declare same-process usecase dependency edges.

Use `source` to preserve code-position mapping. Agents and contributors can jump from the Manifest to the exact contract and implementation files.

## Relationship To Other Outputs

Manifest is the canonical catalog. Markdown docs, Mermaid graph output, and diffs are derived from Manifest data.
