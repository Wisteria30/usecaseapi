# Scaffold

UseCaseAPI includes a scaffold command so versioned contract layout does not depend on memory or tribal rules.

```bash
usecaseapi scaffold orders.place_order --version 1
```

It creates:

```text
app/contracts/orders/place_order/v1.py
app/usecases/orders/place_order.py
tests/test_orders_place_order_v1.py
```

## Create the next major version

If `--version` is omitted, UseCaseAPI scans the existing usecase directory and creates the next available major version.

```bash
usecaseapi scaffold orders.place_order
```

If `v1` already exists, the command creates `v2`.

## Copy a previous version forward

For breaking changes, start from the previous contract and bump only the contract metadata:

```bash
usecaseapi scaffold orders.place_order --from-version 1
```

This copies:

```text
app/contracts/orders/place_order/v1.py
```

into:

```text
app/contracts/orders/place_order/v2.py
```

and updates `version=1` to `version=2`. This keeps the old version intact while giving the new version a concrete starting point.

## Options

```bash
usecaseapi scaffold orders.place_order --version 2
usecaseapi scaffold orders.place_order --from-version 1
usecaseapi scaffold orders.place_order --dry-run
usecaseapi scaffold orders.place_order --force
```

Use `--force` to overwrite generated files. Use `--dry-run` to print what would be created.

The generated test includes a structural Protocol assignment so mypy/pyright can verify that the implementation conforms to the contract:

```python
_impl: PlaceOrder = PlaceOrderImpl()
```
