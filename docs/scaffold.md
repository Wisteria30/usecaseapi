# Scaffold

UseCaseAPI includes a scaffold command so versioned contract layout does not depend on memory or tribal rules.

```bash
usecaseapi scaffold myapp orders.place_order --version 1
```

It creates:

```text
src/myapp/usecases/orders/place_order/v1/place_order_contract.py
src/myapp/usecases/orders/place_order/v1/place_order_usecase.py
tests/usecases/orders/place_order/v1/test_place_order_usecase.py
```

## Create the next major version

If `--version` is omitted, UseCaseAPI scans the existing usecase directory and creates the next available major version.

```bash
usecaseapi scaffold myapp orders.place_order
```

If `v1` already exists, the command creates `v2`.

## Copy a previous version forward

For breaking changes, start from the previous contract and bump only the contract metadata:

```bash
usecaseapi scaffold myapp orders.place_order --from-version 1
```

This copies:

```text
src/myapp/usecases/orders/place_order/v1/place_order_contract.py
```

into:

```text
src/myapp/usecases/orders/place_order/v2/place_order_contract.py
```

and updates `version=1` to `version=2`. This keeps the old version intact while giving the new version a concrete starting point.

## Options

```bash
usecaseapi scaffold myapp orders.place_order --version 2
usecaseapi scaffold myapp orders.place_order --from-version 1
usecaseapi scaffold myapp orders.place_order --dry-run
usecaseapi scaffold myapp orders.place_order --force
```

Use `--force` to overwrite generated files. Use `--dry-run` to print what would be created.

The generated test includes a structural Protocol assignment so mypy/pyright can verify that the implementation conforms to the contract:

```python
usecase: PlaceOrder = PlaceOrderUseCase()
```
