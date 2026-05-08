# Scaffold

UseCaseAPI includes a scaffold command so versioned contract layout does not depend on memory or tribal rules.

```bash
usecaseapi scaffold orders.place_order --version 1
```

By default it creates:

```text
app/contracts/orders/place_order/v1.py
app/usecases/orders/place_order.py
tests/test_orders_place_order_v1.py
```

## Create the next major version

If `--version` is omitted, UseCaseAPI scans the existing contract directory and creates the next available major version.

```bash
usecaseapi scaffold orders.place_order
```

If `v1.py` already exists, the command creates `v2.py`. The implementation file is intentionally not overwritten unless `--force` is passed, because projects often keep one hand-written implementation module and migrate it manually.

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

## Custom roots

```bash
usecaseapi scaffold orders.place_order \
  --version 2 \
  --contracts-root src/myapp/contracts \
  --implementations-root src/myapp/usecases \
  --tests-root tests \
  --contracts-package myapp.contracts \
  --implementations-package myapp.usecases
```

Use `--force` to overwrite generated files. Use `--dry-run` to print what would be created. Use `--no-tests`, `--no-implementation`, or `--no-init` for projects with custom layout.

The generated test includes a structural Protocol assignment so mypy/pyright can verify that the implementation conforms to the contract:

```python
_impl: PlaceOrder = PlaceOrderImpl()
```
