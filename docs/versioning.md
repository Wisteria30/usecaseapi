# Versioning

UseCaseAPI uses explicit major versions.

```text
src/{package}/usecases/{namespace...}/{usecase}/v{major}/{usecase}_contract.py
```

Examples:

```text
src/myapp/usecases/orders/place_order/v1/place_order_contract.py
src/myapp/usecases/orders/place_order/v2/place_order_contract.py
```

The contract key is `name@v{major}`. There is no implicit `latest`.

## Breaking changes

The following require a new major version:

- removing an input field;
- changing an input field type;
- adding a required input field;
- removing an output field;
- changing an output field type;
- changing the Protocol signature;
- changing the contract name;
- changing the declared base error hierarchy;
- removing a declared error;
- replacing a stable dependency edge in a way that changes behavior expected by callers.

## Error versioning

Prefer declaring a usecase-specific base error in `raises`, then documenting leaf errors in `known_errors`.

```python
class PlaceOrderError(UseCaseError):
    code: ClassVar[str] = "orders.place_order"

class InventoryShortage(PlaceOrderError):
    code: ClassVar[str] = "orders.place_order.inventory_shortage"

Contract(..., raises=(PlaceOrderError,), known_errors=(InventoryShortage,))
```

Adding a new leaf error under the declared base is usually compatible because callers can catch the base. Removing or changing the base is breaking.

## Deprecation

Mark old contracts with `deprecated=True` and optionally `superseded_by="orders.place_order@v2"`.
